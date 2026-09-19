# MiSTer hiscore support (hiscore.v) across the five cores

## 1. Summary

- **Psikyo is the only core with hiscore.v integrated.** `E:\Arcade-Psikyo_MiSTer\rtl\hiscore.v` (vendored from JimmyStones/Hiscores_MiSTer, upstream version 14, locally patched for one extra cycle of read latency), instantiated in `E:\Arcade-Psikyo_MiSTer\Psikyo.sv:556-586`, RAM tap in `E:\Arcade-Psikyo_MiSTer\rtl\psikyo_core.sv:238-275`, config block in every `releases/*.mra`.
- **Fuuki, Seta, KonamiGX, JalecoMS32: not implemented.** All four list it as a todo. None has `rtl/hiscore.v` (`find Arcade-*_MiSTer -name hiscore.v` returns only Psikyo's). Fuuki's ROADMAP says the module is "vendored from the Psikyo tree" but the file is not in the Fuuki tree.
- Seta and JalecoMS32 have the **sibling feature, NVRAM save**, using the same hps_io `ioctl_upload_req` / `<nvram index="4">` path but no hiscore.v. KonamiGX loads a 93C46 EEPROM image from `<rom index="2">` and does not persist it yet.
- Reference for a new core: Psikyo. Fuuki's `pause_control.sv` already has the `ext_pause` input intended for it.

## 2. Per-core table

| Core | hiscore.v present | Instantiated | .mra hiscore block | CONF_STR autosave | Pause path for hiscore | Status pointer |
|---|---|---|---|---|---|---|
| Psikyo | `rtl/hiscore.v` (v14 + local patches) | `Psikyo.sv:556` | `<rom index="3">` + `<nvram index="4">` in all 5 `releases/*.mra` | `Psikyo.sv:129` `"H3O[78],Autosave Hiscores,Off,On;"`, masked by `~hs_configured` (`Psikyo.sv:228`) | `Psikyo.sv:514` `pause_core = pause \| hs_pause` -> `maincpu.sv:249` | `README.md:144` lists it as a feature; `docs/ROADMAP.md:248-250` still says "not yet integrated" (stale) |
| Fuuki | no | no (`Fuuki.sv:31` "No hiscore save.") | none in `releases/*.mra` | none | `rtl/pause_control.sv` `ext_pause` (currently JTAG `probe_src[5]`, `Fuuki.sv:392`) | `README.md:121` todo; `docs/ROADMAP.md:702-726` scoped (table of hiscore.dat entries, HS_SCOREWIDTH >= 9) |
| Seta | no | no | none (`<nvram index="4">` present for NVRAM sets only) | none | `Seta.sv:407-417` inline toggle; `rtl/pause_control.sv:1` "Not yet instantiated" | `README.md:416` todo; `docs/ROADMAP.md:726, 992, 1111-1112` |
| KonamiGX | no | no | none | none | no pause logic in `KonamiGX.sv` (only the button name at line 71) | `README.md:145` todo |
| JalecoMS32 | no | no | none (`<nvram index="4" size="8192">` for NVRAM) | none | `MS32.sv:425-437` inline toggle | `Readme.md:128` todo; `docs/ROADMAP.md:559` |

## 3. Mechanism (Psikyo)

### 3.1 Provenance

`E:\Arcade-Psikyo_MiSTer\rtl\hiscore.v:1-7`:

```
//  MAME hiscore.dat support for MiSTer arcade cores.
//  https://github.com/JimmyStones/Hiscores_MiSTer
//  Copyright (c) 2021 Alan Steremberg
//  Copyright (c) 2021 Jim Gregory
```

GPLv3 (`hiscore.v:9-21`). Version history to 0014 at `hiscore.v:24-39`; `localparam HS_VERSION = 14` at `hiscore.v:163`. Acknowledged in `E:\Arcade-Psikyo_MiSTer\README.md:224-226` and `files.qip:56-57`. No THIRD-PARTY.md; the `PROVENANCE.md` files in the tree cover t80, tg68k, sdram, jt10, jt49 only, not hiscore.v.

Local patches (all marked with `// Psikyo:` comments):
- `hiscore.v:113` new state `SM_COMPAREHOLD = 26`; used at `hiscore.v:440-452` and `hiscore.v:493-497` -- one dead cycle because `data_from_ram` is registered in the core.
- `hiscore.v:610-614` and `642-643`: start/end checks skip two cycles instead of one (`wait_timer != CHECK_HOLD && wait_timer != CHECK_HOLD - 1`). Requires `CHECK_HOLD >= 2`.
- `hiscore.v:658-667`: after a successful end check, bounce through `SM_TIMER` (1 cycle) before `SM_CHECKBEGIN` so the config-table outputs reflect the new `counter`.
- No upstream copy in the tree; whether anything else differs from upstream v14 is unverified.

### 3.2 Module parameters (`hiscore.v:43-51`)

| Parameter | Default | Psikyo value (`Psikyo.sv:557-563`) | Meaning |
|---|---|---|---|
| `HS_ADDRESSWIDTH` | 10 | 17 | width of `ram_address`; work RAM is 128 KB at 0xFE0000 so the low 17 bits of the configured 24-bit address are the offset (`Psikyo.sv:546-547`) |
| `HS_SCOREWIDTH` | 8 | 8 | log2 of dump buffer bytes (256); largest Psikyo table is 0x9E (`Psikyo.sv:548`) |
| `HS_CONFIGINDEX` | 3 | 3 (default) | ioctl index of the config download (`<rom index="3">`) |
| `HS_DUMPINDEX` | 4 | 4 (default) | ioctl index of the dump download/upload (`<nvram index="4">`) |
| `CFG_ADDRESSWIDTH` | 4 | 2 | log2 of config table entries; reduced from 16 to 4 to save M10K (`Psikyo.sv:559-561`) |
| `CFG_LENGTHWIDTH` | 1 | 1 | bytes in the entry length field (1 = max 255-byte entries) |

### 3.3 Ports and the Psikyo instantiation (`Psikyo.sv:556-586`)

```
hiscore #(.HS_ADDRESSWIDTH(17), .HS_SCOREWIDTH(8), .CFG_ADDRESSWIDTH(2), .CFG_LENGTHWIDTH(1)) u_hiscore (
	.clk(clk_sys),
	.reset(reset),
	.paused(pause_core),
	.autosave(status[78]),
	.ioctl_upload(ioctl_upload),
	.ioctl_upload_req(ioctl_upload_req),
	.ioctl_download(ioctl_download),
	.ioctl_wr(ioctl_wr),
	.ioctl_addr(ioctl_addr[24:0]),
	.ioctl_index(ioctl_index[7:0]),
	.OSD_STATUS(OSD_STATUS),
	.data_from_hps(ioctl_dout),
	.data_from_ram(hs_data_out),
	.ram_address(hs_address),
	.data_to_hps(ioctl_din),
	.data_to_ram(hs_data_in),
	.ram_write(hs_write),
	.ram_intent_read(hs_read),
	.ram_intent_write(),
	.pause_cpu(hs_pause),
	.configured(hs_configured)
);
```

- `clk` = `clk_sys` (85.909 MHz, `Psikyo.sv:253`). Same clock as hps_io and the core.
- `paused` is the core's combined pause (`pause_core`), fed back so the module's own timers stop while the user has paused (`hiscore.v:782-793`: timer only counts when `paused == 0 || pause_cpu == 1`).
- `pause_cpu` output -> `hs_pause` -> ORed into `pause_core` (`Psikyo.sv:511-514`).
- `ram_intent_write` left unconnected; the core muxes on `hs_write` (`ram_write`) instead. `ram_intent_read` (`hs_read`) is used.
- `ioctl_din`, `ioctl_upload`, `ioctl_upload_req` go to hps_io with `.ioctl_upload_index(8'd4)` (`Psikyo.sv:240-246`). hps_io latches `ioctl_upload_req` until the HPS polls it (`sys/hps_io.sv:152-153, 289-290, 335`).
- `status_menumask` bit 3 = `~hs_configured` (`Psikyo.sv:228`), so the H3 Autosave line is hidden when the .mra carried no index-3 data.
- hps_io must stay in byte mode: `Psikyo.sv:209-216` and `rtl/memory/sdram_download.sv:39-41` -- hiscore.v decodes field positions from `ioctl_addr[2:0]` and byte-cascaded registers (`hiscore.v:244-249, 366-372`), and returns 8-bit upload data.

### 3.4 Plumbing to the RAM tap

`Psikyo.sv:683-685` -> `rtl/psikyo_top.sv:119-124` (ports) and `:284-285` (pass-through) -> `rtl/psikyo_core.sv:87-97` (ports).

`rtl/psikyo_core.sv:238-275` is the tap:

```
wire [15:0] hs_word_addr = hs_address[16:1];
wire        hs_byte_odd  = hs_address[0];
...
wire        hs_access       = hs_read | hs_write;
wire [15:0] workram_a_addr  = hs_access ? hs_word_addr : workram_cpu_addr;
wire        workram_a_wel   = hs_write ? hs_byte_odd  : workram_cpu_wel;
wire        workram_a_weh   = hs_write ? ~hs_byte_odd : workram_cpu_weh;
wire [15:0] workram_a_wdata = hs_write ? {hs_data_in, hs_data_in} : workram_cpu_wdata;
...
dpram #(.ADDR_WIDTH(16), .DATA_WIDTH(16)) u_workram ( .a_addr(workram_a_addr), ... .b_addr(16'd0), .b_rdata(workram_unused_b) );
always_ff @(posedge clk)
	hs_data_out <= hs_byte_odd ? workram_cpu_rdata[7:0] : workram_cpu_rdata[15:8];
```

- Both reads and writes borrow the CPU's port A of the 16-bit work RAM; port B stays tied to a constant. Reason (`psikyo_core.sv:246-254`, `docs/LESSONS_LEARNED.md:620-626`, commit `d10eabc` body): driving port B with a real address made Quartus replicate the array (~102 extra M10K) and the design stopped fitting.
- Byte lane: 68k big-endian, even byte = high half (`psikyo_core.sv:239-242`).
- `hs_data_out` is registered next to the RAM (`psikyo_core.sv:268-275`); this is what the `SM_COMPAREHOLD` / two-cycle-skip patches in hiscore.v compensate for. Commit `548e832` body: "hiscore work-RAM read registered next to the M10K ... removed the design's worst path group (~300 endpoints)".

### 3.5 Runtime behaviour (from the hiscore.v state machine)

- Config download (index 3): header parsed at `hiscore.v:325-341`, entries into four `dpram_hs` tables at `hiscore.v:253-291`; `configured` goes high when the index-3 download ends (`hiscore.v:355-358, 188`).
- Restore: on the falling edge of `reset` with a dump loaded, wait `START_WAIT` then check each entry's start/end sentinel bytes (`hiscore.v:378-388, 589-693`); if any fails, retry after `CHECK_WAIT`; once all pass, write the dump into game RAM (`hiscore.v:695-773`), repeated `WRITE_REPEATCOUNT` times.
- Save: on OSD open (`OSD_STATUS` rising, `hiscore.v:402-406`) the module pauses the CPU, reads all entries into a buffer and compares against the last dump (`hiscore.v:413-502`). If changed and non-zero it copies to the dump buffer and, if `autosave`, pulses `ioctl_upload_req` (`hiscore.v:503-567`). The HPS then reads the dump via index 4 (`hiscore.v:393-399`). With autosave off, the dump is still refreshed and uploaded only when the HPS asks (OSD "Save settings"; that HPS-side behaviour is described in Seta's `docs/ROADMAP.md:966-970` for NVRAM and is not separately verified here).

## 4. .mra layout

Every Psikyo release .mra carries the same two elements. `E:\Arcade-Psikyo_MiSTer\releases\Samurai Aces (World).mra:47-54`:

```
	<rom index="3">
		<part>
		19 9A 57 EF 3F FF 00 02 00 02 00 01 00 0F 10 00
		00 FE 7D 80 9E 00 04 00
		</part>
	</rom>

	<nvram index="4" size="158"/>
```

Decoding per `hiscore.v:122-160`:

Header (16 bytes, `hiscore.v:128-138`), identical in all five Psikyo .mra files:

| Bytes | Field | Value |
|---|---|---|
| `19 9A 57 EF` | START_WAIT | 0x199A57EF cycles (~5.0 s at 85.909 MHz). Commit `548e832` body: raised so the restore "no longer lands during the power-on RAM test, which made Strikers and Tengai report bad RAM". |
| `3F FF` | CHECK_WAIT | 0x3FFF |
| `00 02` | CHECK_HOLD | 2 (minimum for the Psikyo patch, `hiscore.v:450`) |
| `00 02` | WRITE_HOLD | 2 |
| `00 01` | WRITE_REPEATCOUNT | 1 |
| `00 0F` | WRITE_REPEATWAIT | 15 |
| `10` | ACCESS_PAUSEPAD | 16 cycles paused before/after each RAM access |
| `00` | CHANGEMASK | 0 (no mask line follows) |

Entry (8 bytes, `CFG_LENGTHWIDTH=1` format, `hiscore.v:140-149`): `ADDR[4] LEN[1] START[1] END[1] PAD[1]`. The 8th byte is padding, not a pattern; with `CFG_LENGTHWIDTH=2` it becomes the second length byte (`hiscore.v:151-159`).

| Set | Entry bytes | Address | Length | Start | End | `<nvram size>` |
|---|---|---|---|---|---|---|
| samuraia | `00 FE 7D 80 9E 00 04 00` | 0xFE7D80 | 0x9E = 158 | 0x00 | 0x04 | 158 |
| gunbird | `00 FE 3D D0 75 00 2D 00` | 0xFE3DD0 | 0x75 = 117 | 0x00 | 0x2D | 117 |
| s1945 | `00 FE 2A F8 78 2D F8 00` | 0xFE2AF8 | 0x78 = 120 | 0x2D | 0xF8 | 120 |
| tengai | `00 FE 4C B0 48 2D 98 00` | 0xFE4CB0 | 0x48 = 72 | 0x2D | 0x98 | 72 |
| btlkroad | `00 FE 1A F4 4E 00 04 00` | 0xFE1AF4 | 0x4E = 78 | 0x00 | 0x04 | 78 |

`<nvram size>` equals the sum of entry lengths (one entry per game). The HPS loads `config/nvram/<mra name>.nvm` as an index-4 download after the ROM and writes it back on upload. These values are taken from the .mra files; they were not re-checked against MAME's `hiscore.dat` in this survey (no copy of hiscore.dat in any of the five trees).

### Scripts

- Psikyo has **no build_mra.py**; the `releases/*.mra` are hand-maintained. `scripts/validate_mra.py:52-54` only whitelists `nvram` as an element whose text/tail is allowed; it does not check the hiscore block. `scripts/deploy_mra.py` copies files; no hiscore logic.
- Fuuki, Seta, KonamiGX `scripts/mra.py` (docstring, e.g. `E:\Arcade-Fuuki_MiSTer\scripts\mra.py:12-14`) can parse `<part>0A 0B</part>` literal bytes "used for the mod byte and for hiscore configuration blocks", but only the index-0 image is assembled; none of the `build_mra.py` scripts emits a `<rom index="3">` block (grep for hiscore in `build_mra.py` returns nothing in any repo).
- `E:\Arcade-JalecoMS32_MiSTer\scripts\build_mra.py:222-224` and `E:\Arcade-Seta_MiSTer\scripts\build_mra.py:124, 1080-1084` emit `<nvram index="4" .../>` for the NVRAM feature, not hiscore.

## 5. Pause / RAM-tap requirements

- hiscore.v asserts `pause_cpu` before every RAM access and waits `ACCESS_PAUSEPAD` cycles (`hiscore.v:422-426` compare, `591-597` check, `697-703` write) and again before releasing (`hiscore.v:479-482, 761-763`). It assumes the core honours `pause_cpu` so that its writes (and, in Psikyo, its reads) through a shared port cannot collide with the CPU.
- Psikyo honours it: `Psikyo.sv:514` `pause_core = pause | hs_pause` -> `psikyo_top.sv:117` -> `psikyo_core.sv:441-446` `effective_pause` -> `maincpu.sv:249` (`else if (pause) cpu_ce <= 1'b0;`) -- the 68020 clock enable stops; video keeps running (`maincpu.sv:192-195`). Sound CPU is not paused (`README.md:142` "CPU pause button suspends main CPU (only)").
- If a core gives hiscore its own read port, the pause is still needed for the write phase and to keep the compare consistent; Psikyo's choice of sharing the CPU port is a BRAM-budget decision, not a hiscore.v requirement (`psikyo_core.sv:246-254`).
- `paused` input: feed the core's total pause so the START_WAIT/CHECK_WAIT timers freeze under user pause (`hiscore.v:784-786`).
- Seta/Fuuki `pause_control.sv` provides the hook: `assign pause_cpu = pause_latched | ext_pause;` (`E:\Arcade-Fuuki_MiSTer\rtl\pause_control.sv:43`, `E:\Arcade-Seta_MiSTer\rtl\pause_control.sv:36`). `ext_pause` is a level input; Fuuki's `sim/pause_tb/tb_pause.sv:86` names "hiscore RAM access" as its intended source. In Fuuki it is currently wired to JTAG `probe_src[5]` (`Fuuki.sv:387-394`); a hiscore integration would OR `hs_pause` in. Fuuki's CPU pause reaches `maincpu` via `fuuki_core.sv:233` `.pause(pause_cpu | walk_active)`. In Seta, `pause_control.sv` is not instantiated (`pause_control.sv:1-2`); `Seta.sv:417` `pause_core = pause_toggle | status[82] | dbg_rd_en` -> `seta_core.sv:281` `.cpu_run(!pause_cpu)`.
- Read latency: if the tap registers `data_from_ram` (as Psikyo does), the module needs the Psikyo patches and `CHECK_HOLD >= 2`. If the tap is combinational from the BRAM output, stock hiscore.v timing applies (upstream single-cycle skip). Which of the two a new core wants is a timing-closure decision; Psikyo's record says the unregistered path was its worst (`psikyo_core.sv:268-273`).

## 6. Checklist for a new core

1. Copy `E:\Arcade-Psikyo_MiSTer\rtl\hiscore.v` (keep the GPLv3 header); decide whether to keep the Psikyo read-latency patches (register `data_from_ram` next to the RAM) or revert to single-cycle reads. Add to `files.qip`/`.qsf` (`Psikyo.qsf:330`).
2. Confirm hps_io is not in WIDE mode (`Psikyo.sv:209-216`).
3. hps_io: connect `ioctl_upload`, `ioctl_upload_req`, `.ioctl_upload_index(8'd4)`, `ioctl_din` (`Psikyo.sv:240-246`).
4. CONF_STR: `"H<n>O[<bit>],Autosave Hiscores,Off,On;"` with `status_menumask` bit n = `~hs_configured` (`Psikyo.sv:129, 228`).
5. Parameters: `HS_ADDRESSWIDTH` = log2 of the RAM window such that the low bits of the hiscore.dat address are the RAM offset (else subtract a base in the core); `HS_SCOREWIDTH` >= log2(sum of entry lengths) -- Fuuki needs 9 (`E:\Arcade-Fuuki_MiSTer\docs\ROADMAP.md:719-721`); `CFG_ADDRESSWIDTH` >= log2(entry count); `CFG_LENGTHWIDTH` = 2 if any entry exceeds 255 bytes (Fuuki gogomile 0x161, asurabus 0x132 -- so Fuuki needs 2, which changes the .mra entry format to `hiscore.v:151-159`).
6. Pause: OR `pause_cpu` into the CPU's pause (`ext_pause` on `pause_control.sv`), feed the combined pause back to `paused`.
7. RAM tap: mux `ram_address`/`data_to_ram`/`ram_write` onto the work-RAM port with correct byte-lane select for a 16-bit RAM (`psikyo_core.sv:243-259`); return the selected byte on `data_from_ram`. Do not put a real address on a previously constant BRAM port without checking `Block Memory Bits` (`docs/LESSONS_LEARNED.md:620-626`).
8. .mra: `<rom index="3">` with the 16-byte header (`19 9A 57 EF 3F FF 00 02 00 02 00 01 00 0F 10 00` is what Psikyo ships; START_WAIT depends on the game's RAM test) followed by one 8-byte line per hiscore.dat entry; `<nvram index="4" size="<sum of lengths>"/>`.
9. Hardware test: boot with no `.nvm`, get a score, open OSD (autosave on), confirm `config/nvram/<name>.nvm` appears with the right size; reboot and confirm the table is restored after START_WAIT. Also check the game's power-on RAM test still passes (Psikyo commit `548e832`).

## 7. Disagreements / unknowns

- **Task brief vs tree:** the brief says `<nvram index="2" size=...>`; Psikyo uses `<nvram index="4">` (matches `HS_DUMPINDEX=4`). Index 2 is KonamiGX's EEPROM `<rom index="2">` (`KonamiGX.sv:201-206`), unrelated.
- **Entry format:** the brief calls the 8th byte "pattern"; hiscore.v calls it padding (`hiscore.v:143, 149`). No pattern field exists.
- **Psikyo ROADMAP is stale:** `docs/ROADMAP.md:152` and `:248-250` say hiscore.v is "not yet wired"/"not yet integrated"; `README.md:144`, `Psikyo.sv:556`, and the .mra files show it shipped (commit `d10eabc`, 2026-08-30 per `git log`). `docs/ROADMAP.md:180` (savestates section) contradicts the same file by citing hiscore.v as "already proving the pause-and-borrow-a-BRAM-port pattern on hardware".
- **Seta ROADMAP.md:726** says "both prior cores have a working integration to copy"; only Psikyo has one. Fuuki's `docs/ROADMAP.md:704-705` says hiscore.v is "vendored from the Psikyo tree" but `rtl/hiscore.v` is absent from Fuuki and `Fuuki.sv:31` says "No hiscore save."
- **Comment path mismatch:** `Psikyo.sv:210`, `rtl/memory/sdram_download.sv:39` (and the copies in MS32/Fuuki `sdram_download.sv`) refer to `sys/hiscore.v`; the file is `rtl/hiscore.v`.
- **Hardware verification of Psikyo's hiscore:** no document records a save/restore round-trip test. Evidence it ran on hardware is indirect: commit `548e832` body reports the restore landing during the power-on RAM test on Strikers/Tengai and the START_WAIT change; `docs/ROADMAP.md:180` claims it is proven on hardware without citing a test. Treat the end-to-end save/restore as **unverified** in the written record. No simulation testbench includes hiscore.v (`sim/psikyo_core_tb/tb_psikyo_core.sv:46-47`, `sim/psikyo_top_tb/tb_psikyo_top.sv:75-76` tie the port off).
- **hiscore.dat correspondence:** the five .mra entries were not cross-checked against MAME's hiscore.dat here; `README.md:225-226` says they came from it.
- **Upstream diff:** no upstream hiscore.v in any tree; the set of local modifications is taken from the `// Psikyo:` comments only.
- **HPS "Save settings" path with autosave off:** behaviour described only in Seta's NVRAM notes (`E:\Arcade-Seta_MiSTer\docs\ROADMAP.md:966-970`), not verified for the hiscore index.

## Sibling feature: NVRAM save (not hiscore)

- **JalecoMS32:** `E:\Arcade-JalecoMS32_MiSTer\MS32.sv:138-150` -- `nvram_dirty` set on any NVRAM write (`nv_written`), `nvram_save` pulsed on OSD open; `MS32.sv:173-178` `.ioctl_upload_req(nvram_save), .ioctl_upload_index(8'd4), .ioctl_din(nv_rdata)`; `<nvram index="4" size="8192"/>` in every release .mra (emitted by `scripts/build_mra.py:222-224`). No CPU pause; the NVRAM is read through its own port.
- **Seta:** `E:\Arcade-Seta_MiSTer\rtl\seta_core.sv:429-448` -- `nv_armed`/`nv_dirty` latch driven by the game's `$3000f0` write-enable protocol; `nvram_save` pulses on close-after-write; `Seta.sv:187-190` upload index 4; `<nvram index="4" size="256"/>` (zombraid) / `4096` (calibr50). `Seta.sv:722` `dbg_nv_saves`/`dbg_nv_state`/`ioctl_upload`/`OSD_STATUS` are JTAG probe fields for this NVRAM path, not hiscore. `docs/ROADMAP.md:957-975` records a DE10-nano verification of the `.nvm` round trip.
- **KonamiGX:** 93C46 EEPROM image loaded from `<rom index="2">` (`KonamiGX.sv:201-206`); write-back to `.nvm` is a todo (`KonamiGX.sv:14`, `README.md:143`).
