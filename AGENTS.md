## Project Overview

StarryNet is a novel experimentation emulator that enables researchers to conveniently build credible and flexible experimental network environments (ENE) mimicking satellite dynamics and network behaviors of large-scale ISTNs.

For more detailed information, refer to README.md 

### Building and Running

Install python package `starrynet` and executables `sn` and `sn-worker`:
```bash
python3 setup.py install
```

Run local worker:
```bash
sudo sn-worker --workdir test --machine-id 0 --username abc --password 123456
```

Run experiment:
```bash
python3 example.py
```

## Development

### Repository Structure

Focus on the following files and directories:
- `config.json`: sample topology and worker configuration
- `example.py`: Python API example
- `bin/`: entrypoints for CLI `sn` and worker `sn-worker`
- `starrynet/`: library code
- `web/` (DEVELOPING): web interface code

### Rules

- Planning before coding is highly recommended, especially for complex features. All plans should be documented in the `plans/` directory as markdown files to be reviewed by other developers and agents. Each plan should include the motivation, design, and implementation details.
- No compatibility consideration for now, feel free to refactor and break any APIs and data formats.
- Make the codebase and git history clean and organized. No agents/AI related signatures in commit messages.

### Commit Message Format
```
<type>: <subject>

<body>
```