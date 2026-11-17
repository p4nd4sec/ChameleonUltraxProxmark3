> [!NOTE]
> **This is a personal fork of [RfidResearchGroup/ChameleonUltra](https://github.com/RfidResearchGroup/ChameleonUltra)**
> that ports LF features from Proxmark3 to the Chameleon Ultra. It is not an official release.
>
> | | |
> |---|---|
> | Upstream | `https://github.com/RfidResearchGroup/ChameleonUltra` (branch `main`) |
> | Forked from | [`6009a5f`](https://github.com/RfidResearchGroup/ChameleonUltra/commit/6009a5f) (2026-11-11, merge of PR #557) |
> | Work branch | `feat/lf-t55xx-detect` |
>
> **What this fork adds** (full list under `[unreleased]` in [CHANGELOG.md](CHANGELOG.md)):
> - `lf t55xx detect`: T55xx/T5577 modulation, bit rate and block 0 detection (new `LF_T55XX_READ_RAW` command)
> - `lf em 4x05 info / write / wipe / clone --id`: EM4x05/EM4305 using Proxmark3 downlink framing (new `EM4X05_READ_RAW` and `EM4X05_WRITE_WORD` commands)
> - Fixes `lf em 4x05 read` and raw LF captures (`lf sniff`, `lf generic adcread`) that were dropping samples
> - Host-side demodulation in `software/script/{lf_demod,t55xx,em4x05}.py`, with unit tests in `software/script/tests/`
>
> **Comparing with / syncing from upstream:**
> ```sh
> git remote add upstream https://github.com/RfidResearchGroup/ChameleonUltra.git
> git fetch upstream
> git log --oneline upstream/main..HEAD   # commits that exist only in this fork
> git diff upstream/main...HEAD --stat    # files this fork changes
> git merge upstream/main                 # pull in new upstream changes
> ```
>
> The new command IDs live in `data_cmd.h` / `chameleon_enum.py`. Check them for conflicts with upstream before merging.

![logo](docs/images/ultra-logo.png)

![ultra picture](docs/images/ultra-overview.png)

# ChameleonUltra Authorized Distributors

Lyon, France: [Lab401](https://lab401.com/)

Santa Ana, United States: [Hackerwarehouse](https://hackerwarehouse.com/)

Hastings, UK: [KSEC](https://labs.ksec.co.uk/product/proxgrind-chameleon-ultra/)

Montreal, Canada: [TechSecurityTools](https://techsecuritytools.com/product/chameleon-ultra/)

Shenzhen, China: [Sneaktechnology](https://sneaktechnology.com)

Guangdong, China: [MTools Tec](https://shop.mtoolstec.com/)

Lazada One, Singapore: [Aliexpress by RRG](https://proxgrind.aliexpress.com/store/1101312023)

# What is it and how to use ?

Read the [available documentation](https://github.com/RfidResearchGroup/ChameleonUltra/wiki).

# Compatible applications

* [ChameleonUltraGUI](https://github.com/GameTec-live/ChameleonUltraGUI)
* [ChameLab](https://github.com/m0n5ter/ChameLab)
* [Chameleon Ultra (Sailfish OS only)](https://sailfishos-chum.github.io/apps/harbour-chameleon-ultra)
* [Chameleon GO (iOS only)](https://apps.apple.com/us/app/id6802015306)
* [Device console for ChameleonUltra (Web)](https://sec1.dk/phreakbyte.html)
* [MTools BLE](https://github.com/RfidResearchGroup/ChameleonUltra/wiki/mtoolsble)
* [Mifare Chameleon Tool (iOS only, Beta)](https://apps.apple.com/it/app/mifare-chameleon-tool/id6761231484)

# Videos

*Beware some of the instructions might have changed since recording, check the current documentation when in doubt!*

* [Downloading and compiling the official CLI](https://www.youtube.com/watch?v=VGpAeitNXH0)
* [Downloading ChameleonUltraGUI](https://www.youtube.com/watch?v=rHH7iqbX3nY)
* [ChameleonUltraGUI features overview](https://www.youtube.com/watch?v=YqE8wyVSse4)
* [Using ChameleonUltraGUI and the Chameleon Ultra](https://www.youtube.com/watch?v=9jtKNJ5-kVY)
* [MTools BLE - How to clone a card with ChameleonUltra](https://youtu.be/IvH-xtdW1Wk?si=4exqgAAeJ-kxU3aN)

# Official channels

Where do you find the community?
* [RFID Hacking community discord server](https://t.ly/d4_C)
  * Software/chameleon-dev for firmware and clients development discussions
  * Devices/chameleon-ultra for usage discussions
* [GameTec_live discord server](https://discord.gg/DJ2A4wxncK)

Other notable projects:
* [Fantasi](https://fantasi.cloud)
  * [Discord](https://fantasi.cloud/discord)
* [chameleon-ultra.js](https://github.com/taichunmin/chameleon-ultra.js/) 

###### Searching for the docs repo? Find it [here](https://github.com/RfidResearchGroup/ChameleonUltraDocs)
