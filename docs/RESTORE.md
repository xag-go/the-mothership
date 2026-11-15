# Restore from the off-site copy

`install.py offsite` leaves encrypted archives in a folder of its own (default `~/offsite-copy`) that another machine
holds a copy of. This page is how to get back from one of them. The same steps, with your own paths, are written to
`wiki/sops/restore.md` in the base on the first `offsite` run.

## What you need

1. One archive: `offsite-<base name>-<date>-<time>.tar.gz.enc` (openssl) or `.tar.gz.age` (age), and the `.sha256`
   file beside it.
2. The passphrase file (default on the original machine: `~/.config/the-mothership/offsite.key`). Your copy is where
   you put it on the first run: a password manager, or the other machine outside the shared folder. Without it the
   archive cannot be opened by anyone.

If the other machine holds the Syncthing folder as "Receive Encrypted", what is on its disk is unreadable there:
share the folder from it to a machine you trust and enter the folder's encryption password on that machine first.

## What an archive holds

| in the archive | what it is |
|---|---|
| `MANIFEST.txt` | when it was made, each source folder, what was left out for size |
| `vault/` | Skeleton Base's vault: the secret files the base only links to |
| `base-state/` | `.mothership.json`, `.kits.json`, `engines.json`, `projects.json` of the base |
| `backups/<folder>/<newest entry>` | the newest entry of each backup folder of the base and the products |

The base itself is not in it: get it from its git remote or its note sync.

## Steps

1. Check the file: `sha256sum -c ARCHIVE.sha256` (in the folder that holds both).
2. Unpack into an empty folder, never over a live vault:

   ```sh
   python3 install.py offsite --restore ARCHIVE --passphrase-file KEYFILE --to ~/restore
   ```

   Without The Mothership (any machine with the cipher and tar):

   ```sh
   mkdir -p ~/restore && cd ~
   # openssl archive (.enc): OpenSSL 1.1.1+ or LibreSSL 3.1+
   openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -md sha256 -d -pass file:KEYFILE -in ARCHIVE | tar -xzpf - -C restore
   # age archive (.age)
   age -d -i KEYFILE ARCHIVE | tar -xzpf - -C restore
   ```

3. Read `~/restore/MANIFEST.txt`.
4. The vault: move `~/restore/vault` to the vault path (`engines.json` "vault" in the base, else
   `~/.<base folder name>-secret`) and `chmod 700` it. Only when no vault is there.
5. The base: clone it from its git remote, or let the sync bring the notes back.
6. The products: `python3 install.py --base <base> --yes`.
7. In the base: `python3 tools/brain.py doctor` names every vault link that is missing or broken.
8. An older state of a settings file: `~/restore/backups/`.
9. `python3 install.py check`, then `python3 install.py offsite` for a fresh copy from the repaired machine.

## Limits

- `openssl enc` (AES-256-CBC) does not authenticate the data: the `.sha256` file detects damage, not a change made
  on purpose by someone who holds the folder. `age` authenticates; install it for that, before the first run.
- Only the newest entry of each backup folder goes in, and only while the cap (`--max-mb`) allows. Tool sessions,
  transcripts and code repositories are not in the copy: push repositories to a remote.
- A copy nobody has restored is not proven: unpack one into a scratch folder a few times a year.
