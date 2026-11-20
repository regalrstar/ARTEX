# Backup & recovery

## What is protected where

| Data | Where |
| --- | --- |
| Source code, docs, deploy/wifi/engagement scripts | `fork` remote → `github.com/regalrstar/ARTEX` (branch `feat/local-work-recovery`) and commit history in `origin` |
| `data/` (traffic, tasks, transcripts, wordlists), `.env`, `skills/`, `engagements/`, and the standalone pipeline project | Encrypted archive — GitHub release `regalrstar/ARTEX@backup-20261120` (primary, split into parts) and iCloud Drive `~/Library/Mobile Documents/com~apple~CloudDocs/artex-backup/` (secondary) |
| Personal skills | Committed in this repo's `skills/` and in `regalrstar/The-Brown-Death` `skills/` |
| `web/node_modules`, `web/.next` | Not backed up (regenerable); excluded from Time Machine |

iCloud is off-device but is **not** a versioned backup. Time Machine is still the primary
protection against bad edits and deletion.

## Restore

Archive passphrase is stored next to the iCloud copy in `BACKUP-PASSPHRASE.txt` (mode 0600).
Copy it somewhere off this disk too — without it the archives are unreadable.

```sh
gh release download backup-20261120 -R regalrstar/ARTEX -p '*.part-*'
A=artex-*.tar.zst.gpg
cat "$A".part-* | shasum -a 256          # must match the hash below
cat "$A".part-* | gpg -d | zstd -d | tar -xf - -C ~/Developer/artex      # data/, .env, skills, docs
cat "$A".part-* | gpg -d | zstd -d | tar -xf - -C ~/Documents/The\ Black\ Death/artex   # pipeline project
```

Verify before trusting an archive:

```sh
cat "$A".part-* | gpg -d | zstd -t       # exits 0, prints byte count
cat "$A".part-* | gpg -d | zstd -d | tar -tf - | wc -l
```

The 20261114 release is a full self-contained archive of the same shape; keep it as a
rollback point for anything deleted since.

### Last archive

- `artex-20261114-234354.tar.zst.gpg` — 1,751,099,169 bytes, 36,039 files
- sha256 `2233e3d6869ae2e5e4a94f55cca5e6c61090b7f8a8148389069bb19ebcfbc042`
- Uploaded to the release; iCloud copy is local-only until sync resumes (see below).

## Time Machine

No destination is configured. Attach an external disk, then:

```sh
diskutil list                      # identify the volume
sudo tmutil setdestination -a /Volumes/<VOLUME>
sudo tmutil startbackup --auto
```

Already excluded: `web/node_modules`. `data/` is **included** — keep it that way.
