# AIL investigator: portable client and isolated server

This is a small, standard-library Python 3.8+ case tool for a dedicated AIL deployment. It records case notes, copies local evidence into a case folder without opening or executing it, computes SHA-256 hashes, checks those hashes later, and sends **only a selected UTF-8 text file** to AIL's documented import API. It does not crawl, browse, run downloads, or promise anonymity.

## Deployment boundary

Use a dedicated Debian/Ubuntu Linux virtual machine for AIL and its optional crawler. Keep your ordinary host computer outside the collection path. AIL's installer targets Debian/Ubuntu; its web UI is documented at https://localhost:7000. The crawler is a separate Lacus component and requires its own configuration. See [AIL README](../README.md), [HOWTO](../HOWTO.md), and [API documentation](../doc/api.md).

1. Create a dedicated VM with an encrypted virtual disk, a non-admin daily account, no shared folders, and clipboard and drag/drop disabled. Take a clean snapshot. Apply OS updates before collecting anything.
2. Clone this fork **inside the VM**, review the selected commit and its install scripts, initialize its submodules, then follow the upstream Debian/Ubuntu installation steps. Do not run an installer on the ordinary host. Keep the AIL UI and API bound to the VM's loopback interface; verify the actual listener before using it.
3. Change AIL's initial password immediately. Store its API key in a secret manager or temporary environment variable. The AIL API documentation says this key gives access to the entire database.
4. Start with manual text imports. Leave continuous feeds, authenticated crawling, automatic exports, email/webhooks, and optional AI services disabled until each destination and retention rule has been reviewed.
5. If you later enable the Lacus crawler, test its Tor SOCKS5 configuration and outbound traffic **inside the VM** first. AIL's HOWTO explicitly calls out the Tor proxy setting. A VM alone does not prevent clearnet leaks or identify the route a crawler used.
6. Keep raw material in the VM or its encrypted case storage. Export only the minimum facts needed for a report. Do not open downloaded documents on the host. Treat collection, retention, and sharing of personal or illicit content as separate decisions.

The CLI can run on macOS, Linux, or Windows wherever Python 3.8+ is present. The **safe deployment pattern still depends on a capable VM or equivalent isolated Linux machine**. Running AIL directly on an arbitrary laptop is not an equivalent isolation boundary.

## Local case commands

Copy tools/ailkit.py to the machine where you want to keep the case directory. The case directory contains sensitive plaintext notes and copied evidence; use encrypted storage and normal OS access controls.

~~~sh
python3 ailkit.py init ./case-001 --title "Example investigation"
python3 ailkit.py add-file ./case-001 ./sample.txt --source "analyst supplied"
printf '%s\n' "Observed at 2026-10-13T12:00:00Z; source retained in VM" | python3 ailkit.py note ./case-001
python3 ailkit.py verify ./case-001
python3 ailkit.py show ./case-001
~~~

The add-file command prints the SHA-256 digest. The stored file has that digest as its filename. The tool limits each copied file to 50 MiB; larger artifacts need a separate controlled evidence workflow. Notes are taken from stdin to avoid putting their content in the command line. Shell history can still contain source paths and titles.

The hash check detects changes to stored blobs. It does **not** authenticate the source, record who handled it, prevent deletion, or provide a trusted chain of custody. The local JSONL event log can be edited by anyone with write access to the case folder.

## Explicit AIL text import

AIL's documented API has POST /api/v1/import/item and POST /api/v1/get/import/item. Only UTF-8 text of at most 1 MiB is supported by this client. Each import requires a digest already recorded in this case. It never imports a directory automatically.

Connect to an AIL server only through a local loopback endpoint. If the server is inside a VM, establish an SSH local port forward from your computer to the VM; for example, where SSH access is already configured:

~~~sh
ssh -N -L 7000:127.0.0.1:7000 analyst@VM_ADDRESS
~~~

Verify that AIL is actually listening only where intended and that the TLS certificate validates for the name in --ail-url. For a private certificate authority, provide its PEM certificate with --ca-cert. Do not disable TLS verification to make an import work.

Set AIL_API_KEY through a secret manager or a protected interactive prompt, without typing the key into a command that shell history records. Then run:

~~~sh
python3 ailkit.py import-text ./case-001 SHA256_FROM_ADD_FILE --ail-url https://localhost:7000 --ca-cert ./trusted-ca.pem
python3 ailkit.py status ./case-001 UUID_FROM_IMPORT --ail-url https://localhost:7000 --ca-cert ./trusted-ca.pem
~~~

The tool accepts HTTPS loopback origins only, disables HTTP proxy use, rejects redirects, verifies TLS certificates, has a 15-second request timeout, and limits API responses to 64 KiB. It does not display the API key. This is a narrow client guard, not a proof that the VM, AIL, Tor, or its dependencies are secure. A self-signed server certificate may need to be reissued with a localhost subject alternative name before a TLS-valid tunnel can work.

## Checks

Run the focused tests without starting AIL:

~~~sh
python3 -m unittest discover -s tests -p test_ailkit.py
~~~

Then, in the isolated VM, test one harmless text import and status lookup before using real material. Confirm that no API endpoint is reachable from the wider network and that backup and deletion procedures work for the case directory and AIL's own database.
