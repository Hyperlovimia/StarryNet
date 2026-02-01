#encoding: utf-8
import os
import datetime
import glob
import json
import numpy as np
from sgp4.api import Satrec, WGS84
from skyfield.api import load, wgs84, EarthSatellite


def _dist_km_to_delay_ms(dist):
    return dist / (17.31 / 29.5 * 299792.458) * 1000

def to_cbf(lat_long):# the xyz coordinate system.
    lat_long = np.array(lat_long)
    radius = 6371
    if lat_long.shape[-1] > 2:
        radius += lat_long[..., 2]
    theta_mat = np.radians(lat_long[..., 0])
    phi_mat = np.radians(lat_long[..., 1])
    z_mat = radius * np.sin(theta_mat)
    rho_mat = radius * np.cos(theta_mat)
    x_mat = rho_mat * np.cos(phi_mat)
    y_mat = rho_mat * np.sin(phi_mat)
    return np.stack((x_mat, y_mat, z_mat), -1)

# def _bound_gsl(antenna_elevation, altitude):
#     a = 6371 * np.cos(np.radians(90 + antenna_elevation))
#     return a + np.sqrt(np.square(a) + np.square(altitude) + 2 * altitude * 6371)

def _sat_name(shell_id, orbit_id, sat_id):
    return f'SH{shell_id+1}O{orbit_id+1}S{sat_id+1}'

def _gs_name(gid):
    return f'GS{gid}'

def _isl_grid(sat_cbf, name_lst, orbit_num, sat_num):
    # [[ [isl] for every satellite]
    isls_lst = []

    sat_cbf = sat_cbf.reshape(orbit_num, sat_num, 3)
    down_cbf = np.roll(sat_cbf, -1, 2)
    right_cbf = np.roll(sat_cbf, -1, 1)
    delay_down = np.sqrt(np.sum(np.square(sat_cbf - down_cbf), -1)) / (
        17.31 / 29.5 * 299792.458) * 1000  # ms
    delay_right = np.sqrt(np.sum(np.square(sat_cbf - right_cbf), -1)) / (
        17.31 / 29.5 * 299792.458) * 1000  # ms
    for oid in range(orbit_num):
        for sid in range(sat_num):
            # down isl
            down_oid = oid
            down_sid = sid + 1 if sid + 1 < sat_num else 0
            # right isl
            right_oid = oid + 1 if oid + 1 < orbit_num else 0
            right_sid = sid
            isls_lst.append([
                # down isl, (sat_name, delay in ms)
                (name_lst[down_oid * sat_num + down_sid], delay_down[oid, sid]),
                # right isl
                (name_lst[right_oid * sat_num + right_sid], delay_right[oid, sid]),
            ])
    return isls_lst

def _topo_walker_delta(dir, duration, step, shell_lst):
    ts_total = int(duration / step)
    ts = load.timescale()
    since = datetime.datetime(1949, 12, 31, 0, 0, 0)
    start = datetime.datetime(2020, 1, 1, 0, 0, 0)
    epoch = (start - since).days
    GM = 3.9860044e14
    R = 6371393
    F = 18
    ts_lst = [i * step for i in range(ts_total)]
    shift = 0

    sat_lla_t = np.zeros(
        (ts_total, sum(shell['orbit'] * shell['sat']  for shell in shell_lst), 3,),
    )
    isls_lst_t = [[] for t in range(ts_total)]
    names_lst = []
    for i, shell in enumerate(shell_lst):
        inclination = shell['inclination'] * 2 * np.pi / 360
        altitude = shell['altitude'] * 1000
        mean_motion = np.sqrt(GM / (R + altitude)**3) * 60
        orbit_nr, sat_nr = shell['orbit'], shell['sat']
        num_of_sat = orbit_nr * sat_nr

        shell_names = []
        for oid in range(orbit_nr):
            raan = oid / orbit_nr * 2 * np.pi
            for sid in range(sat_nr):
                mean_anomaly = (sid * 360 / sat_nr + oid * 360 * F /
                                num_of_sat) % 360 * 2 * np.pi / 360
                satrec = Satrec()
                satrec.sgp4init(
                    WGS84,  # gravity model
                    'i',  # 'a' = old AFSPC mode, 'i' = improved mode
                    oid * sat_nr + sid,  # satnum: Satellite number
                    epoch,  # epoch: days since 1949 December 31 00:00 UT
                    2.8098e-05,  # bstar: drag coefficient (/earth radii)
                    6.969196665e-13,  # ndot: ballistic coefficient (revs/day)
                    0.0,  # nddot: second derivative of mean motion (revs/day^3)
                    0.001,  # ecco: eccentricity
                    0.0,  # argpo: argument of perigee (radians)
                    inclination,  # inclo: inclination (radians)
                    mean_anomaly,  # mo: mean anomaly (radians)
                    mean_motion,  # no_kozai: mean motion (radians/minute)
                    raan,  # nodeo: right ascension of ascending node (radians)
                )
                sat = EarthSatellite.from_satrec(satrec, ts)
                cur = datetime.datetime(2022, 1, 1, 1, 0, 0)
                t_ts = ts.utc(*cur.timetuple()[:5], ts_lst)  # [:4]:minute，[:5]:second
                geocentric = sat.at(t_ts)
                subpoint = wgs84.subpoint(geocentric)
                for t in range(ts_total):
                    sat_lla_t[t][shift + oid * sat_nr + sid] = (
                        subpoint.latitude.degrees[t],
                        subpoint.longitude.degrees[t],
                        subpoint.elevation.km[t],
                    )
                shell_names.append(_sat_name(i, oid, sid))
        
        names_lst.append(shell_names)
        pos_dir = os.path.join(dir, shell['name'], 'position')
        os.makedirs(pos_dir, exist_ok=True)
        for t, lla_shell in enumerate(sat_lla_t[:, shift:shift + num_of_sat]):
            f = open(os.path.join(pos_dir, '%d.txt' % (t + 1)), 'w')
            for name, lla in zip(shell_names, lla_shell):
                f.write('%s:%f,%f,%f\n' % (name, lla[0], lla[1], lla[2]))
            f.close()
            cbf_shell = to_cbf(lla_shell)
            isls_lst = _isl_grid(cbf_shell, shell_names, orbit_nr, sat_nr)
            isls_lst_t[t].extend(isls_lst)

        shift += num_of_sat

    return sat_lla_t, isls_lst_t, names_lst

def _topo_arbitrary(dir, duration, step, shell_lst):
    #TODO: new format
    topo_t_shell = []
    for i, shell in enumerate(shell_lst):
        name_lst = []
        sat_cbf_t = []
        isls_t = []
        for t, slot in enumerate(shell['timeslots']):
            sat_lla = []
            sat_names = []
            pos_dir = os.path.join(dir, shell['name'], 'position')
            os.makedirs(pos_dir, exist_ok=True)
            f = open(os.path.join(pos_dir, '%d.txt' % (t + 1)), 'w')
            for sid, node in enumerate(slot['position']):
                print(node)
                lla = (node['latitude'], node['longitude'], node['altitude'])
                sat_lla.append(lla)
                name = f'SH{i+1}SAT{sid+1}'
                f.write(name + (':%f,%f,%f\n' % lla))
                sat_names.append(name)
            f.close()
            sat_cbf = to_cbf(sat_lla)   # np array, sat_num * 3
            sat_cbf_t.append(sat_cbf)

            if len(name_lst) == 0:
                name_lst = sat_names
            elif len(name_lst) != len(sat_names):
                raise RuntimeError("satellites change between slots!")

            isls = [list() for _ in range(len(name_lst))]
            for link in slot['links']:
                sid1, sid2 = link['sat1'], link['sat2']
                if sid1 > sid2:
                    sid1, sid2 = sid2, sid1
                delay = np.sqrt(np.sum(np.square(sat_cbf[sid1] - sat_cbf[sid2])))
                isls[sid1].append((name_lst[sid2], delay))
            isls_t.append(isls)
        topo_t_shell.append((shell['name'], name_lst, sat_cbf_t, isls_t))        
    return topo_t_shell

def _gsl_least_delay(sat_cbf_t, sat_names, gs_cbf, antenna_num):
    gsls_lst_t = [[] for t in range(len(sat_cbf_t))]

    # (gs_nr) x (t, sat_nr) -> (gs_nr, t, sat_nr)
    dx = np.subtract.outer(gs_cbf[..., 0], sat_cbf_t[..., 0])
    dy = np.subtract.outer(gs_cbf[..., 1], sat_cbf_t[..., 1])
    dz = np.subtract.outer(gs_cbf[..., 2], sat_cbf_t[..., 2])
    dists_t_lst = np.sqrt(np.square(dx) + np.square(dy) + np.square(dz))
    for gid, dists_t in enumerate(dists_t_lst):
        for t, dists in enumerate(dists_t):
            #TODO: elevation angle bound
            # bound_mask = dists < bound_dis
            bound_mask = dists == dists
            sat_indices = np.arange(len(dists))[bound_mask]
            dists = dists[bound_mask]
            sorted_sat = dists.argsort()
            gsls_lst_t[t].append([
                # (sat_id, delay in ms)
                (sat_names[sat_indices[sat]],
                _dist_km_to_delay_ms(dists[sat]))
                for sat in sorted_sat[:antenna_num]
            ])

    gs_names = [_gs_name(gid) for gid in range(len(gs_cbf))]
    return gsls_lst_t, gs_names

def _write_link_files(dir, isls_lst_t, sat_names_lst, shell_names, gsls_lst_t, gs_names):
    EPS = 1e-2
    TYPE_G, PREFIX_G_4, PREFIX_G_6 = 'G', '9', '2001'
    TYPE_I, PREFIX_I_4, PREFIX_I_6 = 'I', '10', '2002'

    def update_state_single(name, link_dict, nic_state, idx_dict, link_type):
        dels, adds, conns, upds = [], [], [], []
        max_idx = 0

        to_delete = [prev_peer for prev_peer in nic_state if prev_peer not in link_dict]
        for prev_peer in to_delete:
            idx = nic_state.pop(prev_peer)[0]
            max_idx = max(max_idx, idx)
            # del_dict[prev_peer] = idx
            dels.append({'op':'D', 'node':name, 'nic':str(idx)})

        used_indices = {attr[0] for attr in nic_state.values()}
        if used_indices:
            max_idx = max(max_idx, *used_indices)
        skipped_indices = set(range(1, max_idx + 1)) - used_indices

        for peer, delay in link_dict.items():
            attr = nic_state.get(peer)
            if attr:
                if abs(attr[1] - delay) > EPS:
                    upds.append({'op':'U', 'node':name, 'nic':str(attr[0]), 'delay':f'{delay:.2f}', 'type':attr[2]})
                    nic_state[peer] = (attr[0], delay, attr[2], attr[3])
            else:
                link_key = f'{name}-{peer}' if name < peer else f'{peer}-{name}'
                if link_key in idx_dict:
                    gbl_idx = idx_dict[link_key]
                else:
                    gbl_idx = len(idx_dict) + 1
                    idx_dict[link_key] = gbl_idx

                if len(skipped_indices) > 0:
                    nic_idx = skipped_indices.pop()
                else:
                    max_idx += 1
                    nic_idx = max_idx
                    adds.append({'op':'A', 'node':name, 'nic':str(nic_idx)})

                conns.append({
                    'op':'L', 'node':name,
                    'nic':str(nic_idx), 'delay':f'{delay:.2f}', 'peer':peer,
                })
                nic_state[peer] = (nic_idx, delay, link_type, gbl_idx)

        nics = ['None' for _ in range(max_idx)]
        for peer, attr in nic_state.items():
            nics[attr[0]-1] = f"{peer},{attr[1]:.2f}"
        
        # return del_dict, upd_dict, add_dict, conn_dict, nic_lst
        return dels, adds, conns, upds, nics

    isl_indices, gsl_indices = {}, {}
    idx_dict_lst = [(isl_indices, TYPE_I)] * len(shell_names) + [(gsl_indices, TYPE_G)]
    link_dir = os.path.join(dir, 'link')
    names_lst = sat_names_lst + [gs_names]
    name_lst = [name for names in names_lst for name in names]
    nic_states = {name:dict() for name in name_lst }

    # clear old files
    os.makedirs(link_dir, exist_ok=True)
    for file in glob.glob(os.path.join(link_dir, '*')):
        os.remove(file)

    for t, (isls_lst, gsls_lst) in enumerate(zip(isls_lst_t, gsls_lst_t)):
        links_lst = isls_lst + gsls_lst
        links_dict = { name:dict() for name in name_lst }
        for name, links in zip(name_lst, links_lst):
            link_dict = links_dict[name]
            for link in links:
                peer, delay = link
                link_dict[peer] = delay
                links_dict[peer][name] = delay

        del_lst, add_lst, conn_lst, upd_lst = [], [], [], []
        f_state = open(os.path.join(link_dir, f'{t}-state.txt'), 'w')
        # for every group
        for names, (idx_dict, link_type) in zip(names_lst, idx_dict_lst):
            for name in names:
                dels, adds, conns, upds, nics = update_state_single(
                    name, links_dict[name], nic_states[name], idx_dict, link_type)
                del_lst.extend(dels)
                add_lst.extend(adds)
                conn_lst.extend(conns)
                upd_lst.extend(upds)
                f_state.write(f"{name}:")
                f_state.write(' '.join(nics))
                f_state.write('\n')
        f_state.close()

        # after all new links, get peer nic idx and link type
        for conn in conn_lst:
            name, peer = conn['node'], conn['peer']
            attr, peer_attr = nic_states[name][peer], nic_states[peer][name]
            conn['peer_nic'] = peer_attr[0]
            suffix = '10' if name < peer else '40'
            if peer_attr[2] == TYPE_G:
                link_type = TYPE_G
                prefix4, prefix6 = PREFIX_G_4, PREFIX_G_6
                gbl_idx = peer_attr[3]
            elif attr[2] == TYPE_G:
                link_type = TYPE_G
                prefix4, prefix6 = PREFIX_G_4, PREFIX_G_6
                gbl_idx = attr[3]
            else:
                link_type = TYPE_I
                prefix4, prefix6 = PREFIX_I_4, PREFIX_I_6
                gbl_idx = attr[3]

            conn['type'] = link_type
            conn['inet4'] = f'{prefix4}.{gbl_idx >> 8}.{gbl_idx & 0xFF}.{suffix}/24'
            conn['inet6'] = f'{prefix6}:{gbl_idx >> 8}:{gbl_idx & 0xFF}::{suffix}/48'

        json_dict = { 'del':del_lst, 'add':add_lst, 'conn':conn_lst, 'upd':upd_lst }
        with open(os.path.join(link_dir, f'{t}.json'), 'w') as f:
            json.dump(json_dict, f)
        

def gen_topo(dir, duration, step,
             shell_lst, isl_style,
             GS_lat_long, antenna_number, antenna_elevation, gsl_style):
    sat_lla_t, isls_lst_t, names_lst = topo_styles[isl_style](dir, duration, step, shell_lst)
    shell_names = [shell['name'] for shell in shell_lst]
    sat_names = [name for name_shell in names_lst for name in name_shell]
    gsls_lst_t, gs_names = gsl_styles[gsl_style](to_cbf(sat_lla_t), sat_names, to_cbf(GS_lat_long), antenna_number)
    _write_link_files(dir, isls_lst_t, names_lst, shell_names, gsls_lst_t, gs_names)
    return names_lst

def load_pos(path):
    f = open(path, 'r')
    lla_dict = {}
    for line in f:
        toks = line.strip().split(':')
        lla = tuple(map(float, toks[1].split(',')))
        lla_dict[toks[0]] = lla
    f.close()
    return lla_dict

def load_links_dict(path):
    f = open(path, 'r')
    links_dict = {}
    for line in f:
        toks = line.strip().split(':')
        link_lst = []
        for isl in toks[1].split():
            link_lst.append(isl.split(','))
        links_dict[toks[0]] = link_lst
    f.close()
    return links_dict

#TODO: More ISL styles
topo_styles = {
    'Grid': _topo_walker_delta,
    'Arbitrary': _topo_arbitrary,
}
#TODO: More GSL styles
gsl_styles = {
    'LeastDelay':_gsl_least_delay,
}
