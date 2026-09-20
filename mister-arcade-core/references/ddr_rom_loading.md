# Fast ROM loading via DDR3 — survey of five MiSTer arcade cores

Read-only survey of the KonamiGX core, the JalecoMS32 core,
the Seta core, the Fuuki core, the Psikyo core (top-level
trees; `build/` ignored). Line numbers are from the working trees as read.

## 1. Summary

Four of the five cores (Psikyo, Fuuki, Seta, MS32) do fast loading; KonamiGX does not
(the KonamiGX core's `KonamiGX.sv:32` ties every DDRAM output to 0).

The mechanism is the same in all four and is not "ioctl into DDRAM": the `.mra`'s
`<rom index="0" ... address="0x30000000">` makes the HPS (Main_MiSTer, outside these repos)
write the ROM image straight into the DDR3 window at 0x30000000. The core sees
`ioctl_download` rise and fall for index 0 with **no `ioctl_wr` pulses**. On the next reset
release a `rom_loader` reads DDR3 in 8-byte granules through `ddram_phy` and writes them into
the SDRAM download port with the game held in reset. No core keeps ROM in DDR3 at runtime; the
ROM lives in SDRAM in every case. The FPGA never sees the `address=` attribute; the HPS-side
behaviour is inferred from the core comments (`Psikyo.sv:789-792`) and is verified only by the
cores working and by Fuuki's stopwatch number below.

Origin chain (from headers): srg320/Arcade-PsikyoSH2_MiSTer → Psikyo
(`rtl/memory/rom_loader.sv:11`) → Fuuki commit 562c3de "Fast DDR ROM loading" → Seta
(`rtl/memory/rom_loader.sv:7-8`) → MS32 (`rtl/memory/ms32_rom_loader.sv:13-18`,
`MS32.sv:311`).

**Reference implementation: Seta** (the Seta core's `Seta.sv:220-279`,
`rtl/memory/seta_sdram_top.sv:222-269`, `rtl/memory/rom_loader.sv`). Reasons:
- Its `rom_loader` has a generic transform hook (`raw_addr/raw_word` → `xf_addr/xf_data`,
  `rom_loader.sv:26-30, 66-77`) so whatever the byte path does to a word (swizzle, invert)
  is applied identically on the copy path; Fuuki's has no hook, Psikyo's hard-codes one
  transform (ADPCM-A bit swap).
- Its top-level trigger/reset block is the cleanest copy of the pattern and is what MS32
  copied ("After Seta.sv's, from Fuuki", `MS32.sv:311`).
- `length` is a port computed from the layout (`seta_sdram_top.sv:222-229`), not a parameter.
- `ddram_phy.sv` body is byte-identical across MS32/Seta/Fuuki/Psikyo (comment-stripped
  md5 equal); Seta's header is the shortest and states the provenance.

MS32's variant (`ms32_rom_loader.sv`) is the alternative for a core whose download path
scatters single bytes (tile decryption): it replays the DDR3 image byte-by-byte into the
ordinary `ioctl_*` download port so the two paths cannot diverge (`ms32_rom_loader.sv:3-18`).
Slower per byte (three FSM states plus `ioctl_wait` per byte, `ms32_rom_loader.sv:56-74`);
unmeasured.

The only measured load time in any repo: the Fuuki core's `docs/ROADMAP.md:41`
"Asura Blade is playable ~14 s after launch against ~75 s through the ioctl path."
Everything else is unmeasured.

## 2. Per-core table

| Core | Path | Modules (rtl/memory unless noted) | ioctl index for ROM | Held in reset during copy | Load time |
|---|---|---|---|---|---|
| KonamiGX | ioctl → `sdram_download` → SDRAM, byte-paired; DDRAM unused | `gx_sdram_top.sv`, `sdram_download.sv`, `sdram_arbiter.sv`, `gx_rom_port.sv`, `sdram_phy.sv` | 0 (1 = mod byte, 2 = EEPROM image, 254 = DIPs; `KonamiGX.sv:138,148,214,227`) | `core_reset = reset \| ioctl_download \| ~rom_loaded` (`KonamiGX.sv:142`) | unmeasured |
| MS32 | HPS → DDR3; `ms32_rom_loader` replays bytes into `ms32_sdram_top`'s ioctl port (decrypt on the way in) | `ms32_rom_loader.sv`, `ddram_phy.sv`, `ms32_ddram_mux.sv`, `sdram_download.sv`, `ms32_sdram_top.sv` | 0 with `address=`; index 2 capture blob streams bytes (no `address=`, `scripts/build_mra.py:190`); 1 mod byte; 254 DIPs (`MS32.sv:14-15`) | `sys_reset \| ldr_active` into `ms32_core` (`MS32.sv:436`), `core_run` gated (`MS32.sv:420`) | unmeasured ("[x] Fast ROM loading", `Readme.md:127`) |
| Seta | HPS → DDR3; `rom_loader` with swizzle/invert transform → SDRAM download port | `rom_loader.sv`, `ddram_phy.sv`, `gfx_swizzle.sv`, `sdram_download.sv`, `seta_sdram_top.sv` | 0 with `address=` (`scripts/build_mra.py:991`); 1 mod byte; 254 DIPs (`Seta.sv:284-292`) | `core_reset = reset \| ioctl_download \| ~rom_loaded \| ldr_active` (`Seta.sv:232`) | unmeasured; `README.md:46-47` lists it in release 20260913 (commit 546242b) |
| Fuuki | HPS → DDR3; `rom_loader` (no transform) → SDRAM download port | `rom_loader.sv`, `ddram_phy.sv`, `sdram_download.sv`, `fuuki_sdram_top.sv` | 0 with `address=` (`scripts/build_mra.py:640`); 1 mod byte | `core_reset = reset \| ioctl_download \| ~rom_loaded \| ldr_active` (`Fuuki.sv:306`) | **~14 s vs ~75 s** (`docs/ROADMAP.md:41`; method not stated, presumably stopwatch) |
| Psikyo | HPS → DDR3; `rom_loader` (ADPCM-A bit swap) → SDRAM download port | `rom_loader.sv`, `ddram_phy.sv`, `sdram_download.sv`, `gfxrom_byte_reorder.sv`, `psikyo_sdram_top.sv`; `ddram_download.sv`/`ddram_arbiter.sv` exist but are NOT in `files.qip` | 0 with `address=` (all five `releases/*.mra:16`); 1 mod byte | inside `rtl/psikyo_top.sv:206` `core_reset = reset \| ioctl_download \| ldr_active` | unmeasured; `README.md:143`, commit d10eabc |

## 3. Mechanism, with pointers

### 3.1 KonamiGX baseline (SDRAM-only)

- `KonamiGX.sv:32`: `assign {DDRAM_CLK, DDRAM_BURSTCNT, DDRAM_ADDR, DDRAM_DIN, DDRAM_BE, DDRAM_RD, DDRAM_WE} = '0;`
- Reset: `KonamiGX.sv:136-143` — `rom_loaded` sticks after an index-0 download ends;
  `core_reset = reset | ioctl_download | ~rom_loaded`; `mem_reset = reset & ~ioctl_download`.
- `rtl/memory/gx_sdram_top.sv:88-98`: stream address → SDRAM address. Graphics regions are
  spread from MAME's 5-byte rows to 8-byte granules on the way in
  (`spread = base + {off[24:2],3'b000} + off[1:0]` for the four-byte part, `base + {off1,3'b000} + 4`
  for the fifth byte). `:107 assign ioctl_wait = dl_wait | ioctl_wr | dl_wr_q;`
- `rtl/memory/sdram_download.sv:1-4`: "An even byte is held; its odd partner writes both lanes
  in one transaction." Accept condition `:35`: `ioctl_download && ioctl_index == 0 && ioctl_wr`.
  Port list `:6-22`: ioctl_* in, `dl_req/dl_addr[25:0]/dl_data[15:0]/dl_we16/dl_busy` out.
- `rtl/memory/sdram_arbiter.sv:1-3`: download write path "at absolute priority".
- `docs/ROADMAP.md:698` lists Psikyo's `ddram_phy`/`ddram_arbiter`/`ddram_download` as the
  "DDRAM backend" to reuse; nothing is wired. `docs/LESSONS_LEARNED.md:489-495`: choose SDRAM
  over DDRAM for real-time fetch (~26 cycles measured vs 16-cycle budget in a Psikyo bench).

### 3.2 The DDR3 phy (shared, identical body)

`ddram_phy.sv` — MS32 `:20-46`, Seta `:6-30`, Fuuki, Psikyo. Client side:
```
input  req;   // pulse while !busy
input  we;    // 0 = 8-byte granule read, 1 = single-byte write
input  [27:0] addr;   // byte offset from 0x30000000
input  [7:0]  wdata;
output busy, valid;   // valid: 1-cycle pulse, rdata holds the granule
output [63:0] rdata;
```
Address formula (the JalecoMS32 core's `rtl/memory/ddram_phy.sv:55-58`):
```
assign DDRAM_BURSTCNT = 8'd1;
assign DDRAM_ADDR     = {4'b0011, addr_r[27:3]};
assign DDRAM_BE       = we_r ? (8'd1 << addr_r[2:0]) : 8'hFF;
assign DDRAM_DIN      = {8{wdata_r}};
```
BURSTCNT is always 1 ("wider bursts are the obvious throughput improvement", MS32 header
`:17-19`). The loaders use `we=0` only. Protocol was checked against
MiSTer-devel/TSConf_MiSTer's ddram.sv (Psikyo `ddram_phy.sv:1-3`,
`docs/phase1_ddram_map.md:41-60`).

### 3.3 Trigger and reset (Seta as reference; Fuuki, Psikyo, MS32 are the same block)

the Seta core's `Seta.sv:223-260`:
```
wire ldr_active;
reg  rom_loaded = 1'b0, dl_index0_seen = 1'b0, ldr_active_d = 1'b0;
always @(posedge clk_sys) begin
	ldr_active_d <= ldr_active;
	if (ioctl_wr && ioctl_index == 16'd0)  dl_index0_seen <= 1'b1;   // the byte path wrote SDRAM
	if (dl_index0_seen && !ioctl_download) rom_loaded     <= 1'b1;
	if (ldr_active_d && !ldr_active)       rom_loaded     <= 1'b1;   // the copy finished
end
wire core_reset = reset | ioctl_download | ~rom_loaded | ldr_active;
wire mem_reset  = reset & ~ioctl_download;
...
wire dl_index0 = ioctl_download && (ioctl_index == 16'd0);
always @(posedge clk_sys) begin
	ldr_start   <= 1'b0;
	dl_active_d <= dl_index0;
	if (dl_index0 && !dl_active_d)  dl_seen_wr <= 1'b0;
	else if (dl_index0 && ioctl_wr) dl_seen_wr <= 1'b1;
	if (dl_index0 && !dl_active_d) ldr_done <= 1'b0;
	if (reset) ldr_pending <= 1'b1;
	else if (ldr_pending && !ioctl_download && !ldr_active) begin
		ldr_pending <= 1'b0;
		if (!dl_seen_wr && !ldr_done) begin ldr_start <= 1'b1; ldr_done <= 1'b1; end
	end
end
```
Points that the comments say were learned the hard way:
- The copy starts out of **reset release**, not a download-end edge (`Psikyo.sv:795-801`:
  "which is why the first attempt loaded nothing"). MiSTer resets the core once the ROM is
  in DDR3.
- `dl_seen_wr` selects the mode: any `ioctl_wr` on index 0 means a byte-streaming `.mra`, and
  copying DDR3 over it "would destroy a working load" (`Psikyo.sv:803-805`).
- `ldr_done` makes the copy once per index-0 download; otherwise every OSD reset would recopy
  with the bus taken from the rotator (`Psikyo.sv:825-829`, `Fuuki.sv:434-435`).
- `ldr_active` goes into the game's reset, **not** into the memory path's reset: `reset`
  resets the loader itself (`Fuuki.sv:304-305`), and the SDRAM path must stay live through
  the whole download because MiSTer holds RESET for it (`psikyo_top.sv:208-229`, measured:
  the `(reset && ioctl_download)` counter saturated; `ms32_sdram_top.sv:49`; `MS32.sv:350-351`).

Same block: `Fuuki.sv:296-306, 417-441`; `Psikyo.sv:806-835`; `MS32.sv:312-335` (MS32 adds
`dl0_seen` so a capture-only launch with no index-0 download does not start a copy,
`MS32.sv:318-320`, and `core_run` at `:420`).

Where the copy holds the core:
- Seta `Seta.sv:232` → `seta_core.reset(core_reset)` (`:577`).
- Fuuki `Fuuki.sv:306` → `fuuki_core.core_reset` (`:477`).
- Psikyo `rtl/psikyo_top.sv:204-206` (`core_reset = reset | ioctl_download | ldr_active`);
  `Psikyo.sv:647` passes plain `reset`. See §6 for the stale comment at `Psikyo.sv:338-350`.
- MS32 `MS32.sv:436` (`sys_reset | ldr_active`) and `:420`.

### 3.4 The loaders

**Fuuki `rtl/memory/rom_loader.sv`** (`:16-43` ports; `:65-118` FSM). States
`L_IDLE, L_RD, L_RDWAIT, L_WR, L_WRACK, L_NEXT`. One granule read, then four 16-bit writes
with `dl_we16 = 1`; `dl_addr = byte_addr + word_idx*2`; ends when
`byte_addr + 8 >= length`. `length` is a port: `Fuuki.sv:449-451`
`.length(board ? 28'h3880000 : 28'h1180000)` (FG-3 / FG-2 map ends). Header `:1-15`.

**Psikyo `rtl/memory/rom_loader.sv`**: same FSM; `LENGTH` is a parameter `28'h1280000`
(`:16-21`, "the whole SDRAM ROM map ... costs only the copy time of the padding");
`needs_adpcma_swap`/`adpcma_base` ports (`:28-32`), bit 6/7 swap per byte inside the 1 MB
ADPCM-A window (`:73-80`) because "on this path they never pass through the FPGA".
Instantiated `Psikyo.sv:845-853` with `.adpcma_base(25'h0E40000)`; `dl_addr` is 25 bits.
An ISSP probe reports copy progress (`Psikyo.sv:874-891`).

**Seta `rtl/memory/rom_loader.sv`**: FSM gains `L_XF0, L_XF1` (`:38, 66-77`): the raw word
and its address go out on `raw_addr/raw_word`, the caller returns `xf_addr/xf_data` one cycle
later. `seta_sdram_top.sv:237-251` applies the gfx1 word-address swizzle and the
ROMREGION_INVERT inversion, the same transform the byte path applies at `:171-200`.
`ldr_length` per layout (`:222-229`), e.g. `layout_g ? BASE_SUB_G + 0x80000 : ... BASE_X1SND_A + 0x100000`.
Instance `:253-263`; port mux `:265-269` ("the byte path and the copy never write at the same time").

**MS32 `rtl/memory/ms32_rom_loader.sv`**: no SDRAM port; it emits `l_wr/l_addr/l_dout` one
byte per clock paced by `l_wait` (the top's `ioctl_wait`) (`:33-37`), and `MS32.sv:337-341`
muxes those onto `ms32_sdram_top`'s `ioctl_*` inputs:
```
wire        sd_dl    = ioctl_download | ldr_active;
wire [15:0] sd_index = ldr_active ? 16'd0  : ioctl_index;
wire        sd_wr    = ldr_active ? l_wr   : ioctl_wr;
wire [26:0] sd_addr  = ldr_active ? l_addr : ioctl_addr;
wire  [7:0] sd_dout  = ldr_active ? l_dout : ioctl_dout;
```
so the tile decryption (`ms32_sdram_top.sv:35-42, 118-129`) and `sdram_download`'s pairing
run unchanged. `LENGTH = 28'h1FC_0000` (`:21`, end of the map before the objram region).

### 3.5 DDRAM port sharing with the rotator

Every fast-load core also uses DDR3 for `screen_rotate_two`'s HDMI framebuffer. Seta/Fuuki/
Psikyo mux the pins on `ldr_active` and hold the rotator's `DDRAM_BUSY` high for the whole
copy (`Seta.sv:868-886`, `Fuuki.sv:671-674, 698-714`, `Psikyo.sv:938-969`). Reason
(`Psikyo.sv:939-945`, `Fuuki docs/ROADMAP.md:683-687`): the rotator has no reset and samples
`DDRAM_BUSY` to decide whether a write was accepted; between loader transactions BUSY is low,
so it would count phantom writes and leave a stale band in the frame. `DDRAM_CLK` follows the
mux (`Seta.sv:880`).

MS32 also has a runtime DDR3 client (the sprite frame buffer and object-RAM copy in
`ms32_core`), so it has a real mux: `rtl/memory/ms32_ddram_mux.sv` (core vs rotator with a
FIFO for the rotator's pulses, `:1-20`), and the loader's `ddram_phy` replaces the core's
`k_*` side while `ldr_active` (`MS32.sv:375-407, 450-451`); `DDRAM_CLK = clk_sys` always.

### 3.6 SDRAM side

Loader writes go into the same arbiter download port as `sdram_download`:
`fuuki_sdram_top.sv:304-310`, `psikyo_sdram_top.sv:302-310`, `seta_sdram_top.sv:265-269`:
```
assign arb_dl_req  = ldr_active ? ldr_req  : dl_req;
...
assign dl_busy     = ldr_active ? 1'b0        : arb_dl_busy;
assign ldr_busy    = ldr_active ? arb_dl_busy : 1'b0;
```
`sdram_download.sv` body is identical in KonamiGX, MS32, Seta, Fuuki (comment-stripped);
Psikyo's differs only in 25-bit `ioctl_addr`/`dl_addr`. It holds an even byte and writes the
pair as one 16-bit transaction (`dl_we16=1`), or a lone byte when addresses do not pair
(which is what MS32's scattered decrypted bytes hit, `ms32_sdram_top.sv:38-41`).

## 4. .mra layout and byte order

### 4.1 Layout: the .mra image IS the SDRAM map

In all five cores the `<rom index="0">` stream is laid out at the SDRAM byte offsets the
core's `*_sdram_top.sv` reads from, with `<part repeat="N">00</part>` (Psikyo: `FF`) padding
between regions. Each generator parses the RTL's `BASE_*` localparams so the two cannot drift
(Seta `build_mra.py:39-44`; Fuuki `build_mra.py:19-21`; MS32 `build_mra.py:44-53 check_map()`;
KonamiGX `build_mra.py:11-16` via `rtl/gx_board_cfg.sv`). Region images are built from the
driver's `ROM_START` and the interleave `map=` digits are chosen by trying candidates against
that image, not derived (Seta `build_mra.py:8-27`, Fuuki `:7-16`, KonamiGX `:27-32`,
`build_rom_image.py:11-19`, MS32 `extract_romstart.py:9-19`). No repo has an "interleave
decoder" in the RTL: byte order is fixed in the .mra and at the consumer port.

Region tables (as the RTL declares them):

- **MS32** `rtl/memory/ms32_sdram_top.sv:12-20` and `scripts/build_mra.py:44-47`:
  ```
  maincpu   0x000_0000   2 MB    ROM_LOAD32_BYTE x4 -> map 0001/0010/0100/1000
  txtiles   0x020_0000   0.5 MB  decrypted on the way in
  bgtiles   0x028_0000   4 MB    decrypted on the way in
  roztiles  0x068_0000   4 MB
  sprite    0x0A8_0000   17 MB   ROM_LOAD32_WORD x2 -> map 0021/2100
  audiocpu  0x1B8_0000   256 KB
  ymf       0x1BC_0000   4 MB
  objram    0x1FC_0000   64 KB   not downloaded (LENGTH ends here)
  ```
  Regions are filled by repeating the ROM to the region size (MAME tile wrap),
  `ms32_sdram_top.sv:6-10`. Sample: `releases/Tetris Plus 2 (ver 1.0, MegaSystem 32 Version).mra:30-60`.
- **Seta** `rtl/memory/seta_sdram_top.sv:8-16` (layouts A–G) with localparams `:105-154`,
  e.g. C: `maincpu 0, gfx1 2M (4 MB), gfx2 6M, gfx3 8M, x1snd 10M`. Sample `releases/Daioh.mra:13-38`:
  maincpu `interleave output="16" map 01/10`, gfx1 plain parts, gfx2/gfx3 `map="12"`
  (ROM_LOAD16_WORD_SWAP), x1snd plain. 33 of 33 `.mra` carry `address="0x30000000"`.
- **Fuuki** `rtl/memory/fuuki_sdram_top.sv:101-120`:
  ```
  FG2: maincpu 0 (2 MB) audiocpu 0x200000 tiles_l0 0x280000 tiles_l1 0x480000 tiles_l2 0xC80000 sprites 0xE80000 oki 0x1080000   (ends 0x1180000)
  FG3: maincpu 0 (2 MB) audiocpu 0x200000 tiles_l0 0x280000 tiles_l1 0xA80000 tiles_l2 0x1280000 sprites 0x1480000 (32 MB) oki/ymf 0x3480000 (ends 0x3880000)
  ```
  Sample `releases/Asura Blade - Sword of Dynasty (Japan).mra:17-50`: program `output="32"
  map 0001..1000`, bg `0012/1200`, map/sprites `output="16" map="12"`.
- **Psikyo** `docs/phase1_sdram_map.md:129-139`:
  ```
  maincpu   0x000000  0x200000
  audiocpu  0x200000  0x040000
  sprites   0x240000  0x800000
  tiles     0xA40000  0x400000
  samples   0xE40000  0x400000  (adpcma / OPL4 wave)
  adpcmb    0xF40000  0x080000  (inside samples)
  spritelut 0x1240000 0x040000
  total     0x1280000
  ```
  Sample `releases/Gunbird (World).mra:16-45` (program `0012/1200`, gfx `map="12"`, pad `FF`).
  No `.mra` generator script found in `scripts/` (only `validate_mra.py`, `deploy_mra.py`; not read).
- **KonamiGX** per-set bases from `rtl/gx_board_cfg.sv` (`scripts/build_mra.py:100-125
  layout()`): maincpu packed (BIOS at 0, 0x200000.. moved down by 0x1e0000), then k056832 as a
  four-byte part + a one-byte part, then k055673 likewise; the RTL spreads 5-byte rows to 8.
  Sample `releases/Daisu-Kiss (ver JAA).mra:14-37` (`map 0012/1200` program, `0021/2100` sprites).

### 4.2 Byte order

- **DDR3 granule**: little-endian by byte address; "byte i at rdata[8*i +: 8]"
  (`ms32_rom_loader.sv:19`, Fuuki `rom_loader.sv:49-50`, Psikyo `:62-63`). The loaders take
  word k as `gran[k*16 +: 16]` and write it at `byte_addr + 2k`.
- **SDRAM 16-bit word**: `{odd byte, even byte}` — the same packing `sdram_download` produces
  (`data_r <= {ioctl_dout, pend_data}`, KonamiGX `sdram_download.sv:60`). So the two paths
  produce identical SDRAM contents by construction; no loader swaps bytes.
- **Where the swap for a big-endian CPU is done**: at the CPU read port, not in the .mra or
  loader. `fuuki_sdram_top.sv:260-264`: "The download packs a byte pair as {odd, even}, so
  SDRAM holds words little-endian. A 68k program word has the even byte as its high half"
  → `assign cpu_data = {cpu_word_le[7:0], cpu_word_le[15:8]};`. Graphics ports consume
  granules in ascending byte order and need no swap.
- **Psikyo `gfxrom_byte_reorder.sv:30-37`**: reverses the 8 bytes of a granule for the
  tile/sprite row consumers, which take MAME's packed-MSB format; the narrow (CPU/LUT)
  bridges are not routed through it (`:13-20`). Applied at the read port.
- **Seta `gfx_swizzle.sv`**: not a byte swap but a word-address permutation of the sprite
  region, `{h, tile, yh, xh, yl} -> {tile, yh, yl, h, xh}` (`:5-8, 25-27`), applied on both
  download paths at write time (`seta_sdram_top.sv:171-186, 237-251`) so a tile row is one
  granule (`docs/ROADMAP.md:146-147`). Bit 0 (byte within word) is kept so bytes still pair.
  ROMREGION_INVERT gfx1 bytes are inverted on both paths (`:200, :251`).
- **Psikyo ADPCM-A bit 6/7 swap** (samuraia/sngkace): byte path `psikyo_sdram_top.sv:376-382`,
  loader path `rom_loader.sv:73-80`; both keyed on `needs_adpcma_swap = mod_board[1]`
  (`Psikyo.sv:329`).
- **MS32 tile decryption**: byte path only (`ms32_sdram_top.sv:118-129`), which is why its
  loader replays bytes through that path rather than writing words.
- **KonamiGX row spread**: byte path only (`gx_sdram_top.sv:88-98`); a loader for GX would
  have to reproduce it or replay bytes as MS32 does.
- `.mra` `map=` attributes do the interleaving (ROM_LOAD16_BYTE pairs → `01/10`;
  ROM_LOAD16_WORD_SWAP → single part `map="12"`; ROM_LOAD32_BYTE ×4 → `0001..1000`;
  ROM_LOAD32_WORD ×2 → `0012/1200` or `0021/2100`). The digits are proven, not reasoned
  (`docs/LESSONS_LEARNED.md` in every repo: "every interleave Psikyo derived by reasoning was wrong").

## 5. sys/ interface used

- `sys/emu_ports.vh` DDRAM_* ports (quoted at Psikyo `docs/phase1_ddram_map.md:28-41`):
  `DDRAM_CLK, DDRAM_BUSY, DDRAM_BURSTCNT[7:0], DDRAM_ADDR[28:0], DDRAM_DOUT[63:0],
  DDRAM_DOUT_READY, DDRAM_RD, DDRAM_DIN[63:0], DDRAM_BE[7:0], DDRAM_WE`. `sys/sys_top.v:1823-1832`
  wires them to the Avalon `ram_*` signals.
- `sys/ddr_svc.sv` (Sorgelig, 16-bit) is present in all five `sys/` and referenced only from
  `sys/sys_top.v`; none of the emu tops instantiates it. No core uses `sys/ddram.sv` (absent).
- `sys/hps_io.sv:157, 191`: `ioctl_wait` is an input passed straight to `HPS_BUS[37]`; the
  cores hold it from byte acceptance until ready (`ddram_download.sv:7-16`). `hps_io.sv:669-695`
  (`FIO_FILE_TX`, `FIO_FILE_TX_DAT`): `ioctl_addr` resets to 0 at transfer start and increments per
  byte; nothing in `sys/` handles `address=`. That attribute is consumed by Main_MiSTer on the
  HPS, which is not in these repos: **unverified here** beyond the cores' comments and behaviour.
- ioctl_wait usage during the copy: Seta/Fuuki/Psikyo do not drive `ioctl_wait` from the
  loader (no bytes arrive). MS32's loader consumes `sd_wait` (= `ms32_sdram_top.ioctl_wait`)
  as its pacing (`MS32.sv:413`, `ms32_rom_loader.sv:65-66`, `ms32_sdram_top.sv:149-153` adds
  `ioctl_wr_q` to cover the pipeline register).

## 6. Shared modules — provenance and which is newest

| File | Bodies | Header/provenance |
|---|---|---|
| `ddram_phy.sv` | MS32 = Seta = Fuuki = Psikyo (comment-stripped md5 `3314a4c8…` all four) | Psikyo original ("verified against TSConf's ddram.sv", `:1-3`); Fuuki `:3-4` "Vendored from Psikyo"; Seta `:4` "From Fuuki (562c3de), via Psikyo"; MS32 `:3-7` "Copied unchanged from Seta, which vendored it from Fuuki (562c3de), which took it from Psikyo". Newest = MS32; all functionally the same, burst 1. |
| `rom_loader.sv` | Three variants + MS32's byte replayer | Psikyo (parameter LENGTH, ADPCM swap) → Fuuki (`length` port, no transform; 34 stripped lines differ from Seta's) → Seta (`length` port + `raw_/xf_` transform hook, two extra states) → MS32 `ms32_rom_loader.sv` (replays into the ioctl port). Seta's is the most general; MS32's the safest when the byte path scatters bytes. |
| `sdram_download.sv` | KonamiGX = MS32 = Seta = Fuuki; Psikyo 25-bit addresses | Psikyo's header `:1-9` refers to `ddram_download.sv` for the reasoning. |
| Trigger block in the top | Same text in Fuuki/Seta/Psikyo; MS32 adds `dl0_seen` | `MS32.sv:311` "After Seta.sv's, from Fuuki". |
| `ddram_download.sv`, `ddram_arbiter.sv` | Psikyo only | Phase-1 DDRAM-backed design, pivoted off (`docs/phase1_ddram_map.md:3-12`); **not in `Psikyo/files.qip`** (only `ddram_phy.sv:61`, `rom_loader.sv:62`, `gfxrom_byte_reorder.sv:79`). |

## 7. Checklist for a new core

0. **Every `<part>` carries its `crc`**, taken from the driver's `ROM_START`, and every zip
   attribute lists the cascade: the set's own zip, then the parent or merged zip, then a BIOS zip
   (`zip="set.zip|parent.zip|bios.zip"`). The CRC is what identifies a dump; a name is only one
   zip's spelling of it, and a directory inside the zip is ignored. That is how the loader finds
   ROMs in merged, renamed and split sets, and `scripts/mra.py` does the same so a testbench and
   the board accept exactly the same zips. `md5="none"` on the `<rom>` element is separate: it
   skips the whole-image hash, and does not replace the per-part CRCs.
1. `.mra`: emit `<rom index="0" zip=… md5="none" address="0x30000000">` from the generator
   (Seta `build_mra.py:986-991`). Omit it for inline-hex test `.mra` and for anything that
   must stream bytes (MS32 capture blobs, `build_mra.py:187-190`). Keep the byte path working.
2. Top: `ddram_phy` with `.we(1'b0)`, `.clk(clk_sys)`; `DDRAM_CLK = clk_sys` (or the mux
   `ldr_active ? clk_sys : rot_DDRAM_CLK`); mux all DDRAM_* on `ldr_active`; feed the rotator
   `DDRAM_BUSY | ldr_active` (`Seta.sv:868-886`). If DDR3 has a runtime client, add a real
   mux (`ms32_ddram_mux.sv`).
3. Copy the trigger block verbatim (`Seta.sv:235-260`): `dl_seen_wr`, `ldr_pending` set on
   reset, `ldr_start` on reset release when no byte arrived, `ldr_done` once per index-0
   download.
4. `rom_loaded` sticky from either path; `core_reset = reset | ioctl_download | ~rom_loaded | ldr_active`;
   memory-path reset `reset & ~ioctl_download`, never including `ldr_active`
   (`Fuuki.sv:304-306`, `psikyo_top.sv:208-237`).
5. Loader: Seta's `rom_loader` if the byte path transforms words (wire the same transform to
   `raw_*/xf_*`); Fuuki's if it does nothing; MS32's replayer if the byte path scatters single
   bytes (decrypt, KonamiGX-style row spread). `length` = end of the SDRAM map for the board.
6. In `*_sdram_top`: mux `ldr_*` onto the arbiter download port on `ldr_active`
   (`fuuki_sdram_top.sv:304-310`), `ldr_busy = ldr_active ? arb_dl_busy : 0`.
7. Grep every flag derived from `ioctl_wr` (debug gates, `dl_done`) and add the copy-end
   edge (`LESSONS_LEARNED.md` "[Fuuki] A debug gate that keys off the load path dies…",
   Fuuki `:814`, Seta `:1245`, MS32 `:1410`, KonamiGX `:1519`).
8. Add a loader ISSP probe if bring-up is blind (`Psikyo.sv:874-891`).
9. Measure: no core has an in-RTL timer; Fuuki's figure is external. Add one if the number matters.

## 8. Disagreements and unknowns

- **Psikyo comment vs code.** `Psikyo.sv:338-350` says `ldr_active` is not in any reset and that
  `rom_loader.sv`'s header claim "core held in reset during a copy" "describes an intent the
  design does not implement". `rtl/psikyo_top.sv:204-206` does implement it
  (`core_reset = reset | ioctl_download | ldr_active`) while keeping `sdram_reset` separate
  (`:237`). The top-level comment is stale or is talking only about the `reset` input.
- **Psikyo ROADMAP stale.** `docs/ROADMAP.md:251-256` lists "Fast ROM loading via DDR3" as
  not done ("currently streams straight into the onboard SDR SDRAM"); `README.md:143` and
  commit d10eabc say it is in, and all five `.mra` carry `address=`.
- **Psikyo `ddram_download`/`ddram_arbiter`** are described as "kept" (`phase1_ddram_map.md:9-10`)
  and listed as a reuse candidate in `KonamiGX/docs/ROADMAP.md:698` and
  `MS32/docs/ROADMAP.md:552`, but are not compiled anywhere.
- **Size wording.** Psikyo `rom_loader.sv:4` "~14MB", `Psikyo.sv:828` "18.5MB", `LENGTH = 0x1280000`
  (= 18.5 MiB). Cosmetic.
- **Load-time claims.** Fuuki `docs/ROADMAP.md:41` (~14 s vs ~75 s) is the only number; method
  unstated. Seta `build_mra.py:49-52` "a second or two of load time" for padding is an estimate.
  MS32's byte-replay loader is slower per byte than the word loaders by construction; unmeasured.
- **HPS behaviour** for `address=` (DMA into 0x30000000, no `ioctl_wr`) is asserted by the
  core comments only; Main_MiSTer source is not in these repos.
- **KonamiGX** carries the "[Fuuki] fast DDR ROM load" lesson (`docs/LESSONS_LEARNED.md:1519`)
  by copy although it has no fast load.
- **`E:\MiSTer-CoreSkill\mister-arcade-core\SKILL.md:77`** references `references/ddr_rom_loading.md`;
  that file does not exist (only `pcb_video_reference.md` is in `references/`).
