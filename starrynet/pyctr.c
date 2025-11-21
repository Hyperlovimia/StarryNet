#include <Python.h>

#ifndef _GNU_SOURCE
# define _GNU_SOURCE
#endif

#include <unistd.h>
#include <sched.h>
#include <syscall.h>
#include <fcntl.h>
#include <sys/mount.h>
#include <sys/wait.h>
#include <sys/eventfd.h>
#include <sys/mman.h>

#include <signal.h>
#include <errno.h>
#include <string.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>

const int NS = CLONE_NEWNS|CLONE_NEWPID|CLONE_NEWIPC|CLONE_NEWUTS;
char env_lklpath[] = "LKL_PATH=/root/starlink-Grid-LeastDelay/liblkl-posix.so";

static int child_err(const char *prefix, int write_fd) {
    int err = errno;
    const char *error_msg = strerror(err);
    write(write_fd, prefix, strlen(prefix));
    write(write_fd, error_msg, strlen(error_msg));
    close(write_fd);
    return err;
}

static int set_err_msg(const char *prefix, char *msg_buf, size_t max_len) {
    int err = errno;
    snprintf(msg_buf, max_len, "%s: %s", prefix, strerror(err));
    return err;
}

// in child process with new namespace
static int container_init(
    const char* newroot,
    const char* overlay_opt,
    const char* hostname,
    const char* preload_path,
    int err_fd
    ) {
    const char STDOUT_FILE[] = "stdout.log";
    const char STDERR_FILE[] = "stderr.log";
    int flags;
    char env_preload[256], env_instance[256];

    flags = fcntl(err_fd, F_GETFD);
    flags |= FD_CLOEXEC;
    fcntl(err_fd, F_SETFD, flags);

    if(chdir(newroot) != 0) {
        return child_err("chdir failed: ", err_fd);
    }
    // pivot root
    // https://unix.stackexchange.com/questions/456620/how-to-perform-chroot-with-linux-namespaces
    if(syscall(SYS_pivot_root, ".", ".") != 0) {
        return child_err("pivot_root failed: ", err_fd);
    }
    if(chroot(".") != 0) {
        return child_err("chroot failed: ", err_fd);
    }
    if(umount2 (".", MNT_DETACH) != 0) {
        return child_err("umount2 failed: ", err_fd);
    }
    // mount proc
    if(mount("proc", "/proc", "proc", MS_NOSUID|MS_NOEXEC|MS_NODEV, NULL) != 0) {
        return child_err("mount /proc failed: ", err_fd);
    }
    if(mount("sysfs", "/sys", "sysfs", MS_NOSUID|MS_NOEXEC|MS_NODEV, NULL) != 0) {
        return child_err("mount /sys failed: ", err_fd);
    }
    if(mount("none", "/dev", "devtmpfs", MS_NOSUID|MS_STRICTATIME, "mode=755") != 0) {
        return child_err("mount /dev failed: ", err_fd);
    }
    // new session, detach to become a daemon process 
    if(setsid() < 0) {
        return child_err("setsid failed: ", err_fd);
    }

    freopen(STDOUT_FILE, "w", stdout);
    freopen(STDERR_FILE, "w", stderr);

    // other miscellaneous configuration, maybe warning is better choice
    if(signal(SIGCLD, SIG_IGN) < 0) {
        return child_err("ignore SIGCLD failed: ", err_fd);
    }
    if(sethostname(hostname, strlen(hostname))) {
        return child_err("sethostname failed: ", err_fd);
    }
    if(clearenv() != 0) {
        return child_err("clearenv failed: ", err_fd);
    }
    shm_unlink(hostname);

    if(snprintf(env_preload, sizeof(env_preload), "LD_PRELOAD=%s", preload_path) <= 0
    || putenv(env_preload)
    || snprintf(env_instance, sizeof(env_instance), "LKL_INSTANCE=%s", hostname) <= 0
    || putenv(env_instance)
    || putenv(env_lklpath)) {
        return child_err("putenv LD_PRELOAD failed: ", err_fd);
    }
    // sleep infinity, need a process with low resource requirement
    execlp("sleep", "sleep", "inf", NULL);
    // should not be executed here
    return child_err("execlp failed: ", err_fd);
}

// in child process
int container_enter(
    pid_t ctr_pid, const char* hostname, const char* preload_path, char *const* argv,
    char *err_msg, size_t max_len) {
    int pid_fd, ret;
    char env_preload[256], env_instance[256];

    pid_fd = syscall(SYS_pidfd_open, ctr_pid, 0);
    if(pid_fd < 0) {
        return set_err_msg("pidfd_open", err_msg, max_len);
    }

    ret = setns(pid_fd, NS);
    close(pid_fd);
    if(ret != 0) {
        return set_err_msg("setns", err_msg, max_len);
    }
    
    if(snprintf(env_preload, sizeof(env_preload), "LD_PRELOAD=%s", preload_path) <= 0
    || putenv(env_preload)
    || snprintf(env_instance, sizeof(env_instance), "LKL_INSTANCE=%s", hostname) <= 0
    || putenv(env_instance)
    || putenv(env_lklpath)) {
        return set_err_msg("put environment variables failed", err_msg, max_len);
    }

    execvp(argv[0], &argv[0]);
    return set_err_msg("execvp", err_msg, max_len);
}

// in parent process
// on success, ret > 0 means child pid.
// ret < 0 for parent err, ret == 0 for child err
static int container_run_inner(
    const char *base_dir, const char *hostname, const char *preload_path,
    char *chd_err, size_t max_len) {
    // 0755
    const mode_t MODE = S_IRWXU | (S_IRGRP|S_IXGRP) | (S_IROTH|S_IXOTH);
    const char* UPPER_DIR = "upper";
    const char* WORK_DIR = "work";
    const char* NEWROOT = "rootfs";

    if(access(base_dir, F_OK) && mkdir(base_dir, MODE)) return -1;

    int dir_fd = open(base_dir, O_RDONLY);
    if(dir_fd < 0) return -1;
    if((faccessat(dir_fd, UPPER_DIR, F_OK, 0) && mkdirat(dir_fd, UPPER_DIR, MODE))
    || (faccessat(dir_fd, WORK_DIR, F_OK, 0) && mkdirat(dir_fd, WORK_DIR, MODE))
    || (faccessat(dir_fd, NEWROOT, F_OK, 0) && mkdirat(dir_fd, NEWROOT, MODE))) {
        close(dir_fd);
        return -1;
    }
    if(close(dir_fd) != 0) return -1;

    char overlay_opt[PATH_MAX * 3];
    char new_root[PATH_MAX];
    snprintf(overlay_opt, sizeof(overlay_opt),
        "lowerdir=/,upperdir=%s/%s,workdir=%s/%s",
        base_dir, UPPER_DIR, base_dir, WORK_DIR);
    snprintf(new_root, sizeof(new_root), "%s/%s", base_dir, NEWROOT);
    
    if(mount("none", "/", NULL, MS_PRIVATE|MS_REC, NULL) != 0) {
        int err = errno;
        snprintf(chd_err, max_len, "mount rprivate / failed: %s", strerror(err));
        return err;
    }
    // mount overlay
    if(mount("overlay", new_root, "overlay", 0, overlay_opt) != 0) {
        int err = errno;
        snprintf(chd_err, max_len, "mount overlay failed: %s", strerror(err));
        return err;
    }
    // if(mount("none", newroot, NULL, MS_PRIVATE|MS_REC, NULL) != 0) {
    //     return child_err("mount rprivate newroot failed: ", err_fd);
    // }

    int err_fds[2], event_fd;
    if(pipe(err_fds) != 0 || (event_fd = eventfd(0, 0)) < 0) return -1;
    
    pid_t pid = fork();
    if(pid < 0) {
        close(err_fds[0]), close(err_fds[1]), close(event_fd);
        return -1;  
    } else if(pid == 0) {
        close(err_fds[0]);
        if(unshare(NS) != 0) {
            close(event_fd);
            exit(child_err("unshare failed: ", err_fds[1]));
        }
        pid = fork();
        if(pid < 0) {
            close(event_fd);
            exit(child_err("second fork failed: ", err_fds[1]));
        } else if(pid == 0) {
            close(event_fd);
            exit(container_init(new_root, overlay_opt, hostname, preload_path, err_fds[1]));
            // should not execute here
        }
        close(err_fds[1]);
        uint64_t pid_u64 = pid;
        write(event_fd, &pid_u64, sizeof(pid_u64));
        close(event_fd);
        exit(0);
        // should not execute here
    }
    
    close(err_fds[1]);
    ssize_t len = read(err_fds[0], chd_err, max_len-1);
    // anyway, child should exit immediately 
    waitpid(pid, NULL, 0);
    if(len > 0) {
        chd_err[len] = '\0';
        close(err_fds[0]), close(event_fd);
        return 0;
    }

    // receive grandchild pid from child
    uint64_t pid_u64;
    if(read(event_fd, &pid_u64, sizeof(pid_u64)) == sizeof(pid_u64))
        pid = pid_u64;
    else
        pid = -1;

    close(err_fds[0]), close(event_fd);
    return pid;
}

// in parent process
// on success, ret > 0 means child pid, need to be waited and recycled
// ret < 0 for parent err, ret == 0 for child err
static int container_subprocess_exec(
    pid_t ctr_pid, const char* hostname, const char* preload_path,
    char *const* argv, char *err_msg, size_t max_len) {
    int err_fds[2], err, flags;
    pid_t pid;
    ssize_t err_len;

    if(pipe(err_fds) != 0) {
        set_err_msg("pipe", err_msg, max_len);
        return -1;
    }

    pid = fork();
    if(pid < 0) {
        set_err_msg("fork", err_msg, max_len);
        close(err_fds[0]), close(err_fds[1]);
        return -1;
    } else if(pid == 0) { // in child process
        close(err_fds[0]);
        flags = fcntl(err_fds[1], F_GETFD);
        if(flags < 0)
            exit(child_err("fcntl F_GETFD: ", err_fds[1]));
        flags |= FD_CLOEXEC;
        if(fcntl(err_fds[1], F_SETFD, flags) < 0)
            exit(child_err("fcntl F_SETFD: ", err_fds[1]));
        err = container_enter(ctr_pid, hostname, preload_path, argv, err_msg, max_len);
        // should not be executed if success
        write(err_fds[1], err_msg, strlen(err_msg));
        exit(err);
    }
    close(err_fds[1]);

    err_len = read(err_fds[0], err_msg, max_len-1);
    if(err_len > 0) {
        err_msg[err_len] = '\0';
        waitpid(pid, NULL, 0);
        pid = 0;
    }
    close(err_fds[0]);
    return pid;
}

// ========================Python wrapper========================

static PyObject *container_run(PyObject *self, PyObject *args) {
    const char *base_dir = NULL;
    const char *hostname = NULL;
    const char *preload_path = NULL;
    char chd_err[256];
    int pid;

    if (!PyArg_ParseTuple(args,
        "sss:container_run(base_dir, hostname, preload_path)",
        &base_dir, &hostname, &preload_path))
        return NULL;

    pid = container_run_inner(base_dir, hostname, preload_path, chd_err, sizeof(chd_err));
    if(pid < 0) {
        PyErr_SetFromErrno(PyExc_OSError);
        return NULL;
    } else if (pid == 0) {
        PyErr_SetString(PyExc_ChildProcessError, chd_err);
        return NULL;
    } else { // normal case
        return PyLong_FromLong(pid);
    }
}

static PyObject *container_exec(PyObject *self, PyObject *args) {
    int pid;
    const char *hostname = NULL;
    const char *preload_path = NULL;
    PyObject *cmdline;
    int no_return = 0;
    Py_ssize_t argc;
    char **argv;
    char err_msg[256];

    if(!PyArg_ParseTuple(
        args,
        "issO|p:container_exec(container_pid, hostname, preload_path, cmdline, no_return)",
        &pid, &hostname, &preload_path, &cmdline, &no_return))
        return NULL;
    if(!PySequence_Check(cmdline) || (argc = PySequence_Size(cmdline)) <= 0) {
        PyErr_SetString(PyExc_TypeError, 
            "argument 2 \"cmdline\" must be sequence with length >= 1");
        return NULL;
    }

    argv = malloc((argc + 1) * sizeof(*argv));
    for(Py_ssize_t i = 0; i < argc; i++) {
        argv[i] = PyBytes_AsString(PySequence_ITEM(cmdline, i));
        if(argv[i] == NULL) {
            free(argv);
            return NULL;
        }
    }
    argv[argc] = NULL;

    if(no_return) {
        container_enter(pid, hostname, preload_path, argv, err_msg, sizeof(err_msg));
        // should not be executed if success
        PyErr_SetString(PyExc_OSError, err_msg);
    } else {
        int sub_pid = container_subprocess_exec(pid, hostname, preload_path, argv, err_msg, sizeof(err_msg));
        free(argv);

        if(sub_pid < 0) {
            PyErr_SetString(PyExc_OSError, err_msg);
        } else if(sub_pid == 0) {
            PyErr_SetString(PyExc_ChildProcessError, err_msg);
        } else {
            int status;
            waitpid(sub_pid, &status, 0);
            if(WIFEXITED(status)) {
                return PyLong_FromLong(WEXITSTATUS(status));
            } else if(WIFSIGNALED(status)) {
                PyErr_Format(PyExc_ChildProcessError, "subprocess killed by signal %d", WTERMSIG(status));
            } else {
                PyErr_SetString(PyExc_ChildProcessError, "subprocess terminated abnormally");
            }
        }
    }
    
    return NULL;
}

static PyMethodDef methods[] = {
    {"container_run",  container_run, METH_VARARGS, "run a simplified container"},
    {"container_exec", container_exec, METH_VARARGS, "exec command in container"},
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT,
    "pyctr",   /* name of module */
    NULL, /* module documentation, may be NULL */
    -1,       /* size of per-interpreter state of the module,
                 or -1 if the module keeps state in global variables. */
    methods
};

PyMODINIT_FUNC PyInit_pyctr(void) {
    return PyModule_Create(&module);
}
