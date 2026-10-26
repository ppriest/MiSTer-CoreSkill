# Encrypted and scrambled ROMs

MAME decrypts in a driver's `init_*` or in a device after load. The core has to produce the same
bytes the CPU or chip sees, and the method is the same in every core that has done it: transcribe,
prove, then generate.

1. **Transcribe MAME's transform into a Python model** (NixPirates `scripts/decrypt_model.py`, MS32
   the `jalcrpt.cpp` model, GX `scripts/k056734/esccipher.py`).
2. **Prove it byte for byte against the regions MAME holds after init**, for every set, not one.
   Dump them with a Lua script at the first frame (NixPirates `scripts/mame/dumpregions.lua`).
3. **Generate the RTL's tables from the model** (NixPirates `rtl/np_decrypt.svh`), so the proof
   covers the RTL's constants. Then compare the RTL's output with the same regions in a bench.
4. **Every remaining difference from MAME's region is named.** NixPirates: MAME's protection patch at
   0x62c0, applied on the CPU read path so the SDRAM holds the dumped ROM (`MAME_KLUDGES.md`).

Read the transform against the buffer MAME applies it to. `romload.cpp` byte-swaps a big-endian
region onto a little-endian host before `init_*` runs, so `i & 1` in an init is the 68000's high
byte, not the odd file byte (LESSONS_LEARNED, "ROM formats").

## Where the transform goes

| Where | When | Cores |
|---|---|---|
| Download path, as wiring | address and data permutations, and XORs by address | NixPirates, DecoMLC avengrgs samples |
| Download path, scattered bytes | a linear address map that inverts | MS32 |
| At fetch, raw ROM in SDRAM | a transform per word that the fetch path can afford | DecoMLC DE156 sets |
| Run the security chip | the chip runs code, or its output depends on game state | KonamiGX 056734 (ESC) |

- **At load, as wiring.** NixPirates: every ROM is scrambled in address and data, in four transforms.
  Encrypted byte *i*, bit-permuted, written to a bit permutation of *i*, gives MAME's image. The
  loader's decryption is therefore wiring, with no table and no logic. The program ROM's
  permutation is inverted per byte lane. Check the load-time form in the model as well as the
  gather form MAME uses; they are different code. DecoMLC's avengrgs sample ROM is an address
  bitswap only: wire it on the chip's address lines, with no copy.
- **At load, scattered.** MS32's tile transform is `dest[i] = src[L(i ^ ax)] ^ (i & 0xff) ^ dx`,
  where `L` is GF(2)-linear on 19 or 20 address bits.
  - Linearity was checked on random pairs, and invertibility by Gaussian elimination.
  - Each incoming byte at stream offset `j` is then written to `L⁻¹(j) ^ ax`, about 40 lines of RTL.
  - The key pair is chosen by an `.mra` mod byte, which must come before the ROM in the `.mra`
    (`<rom index="1">` listed before `index="0"`).
  - A byte-scattering download path needs the byte-replay DDR3 loader (`ddr_rom_loading.md`,
    MS32's `ms32_rom_loader.sv`).
- **At fetch.** DE156 (DecoMLC): `deco156.cpp`'s transform applies at fetch:
  - a per-word address XOR cascade;
  - 16 two-bit data XORs by address;
  - four 32-bit bitswaps by word index.

  Deco156Simple's `jtosman_deco156.v` does it at fetch, so SDRAM holds the dump. All 262,144 words
  of four sets equalled MAME's decrypted region. Choose fetch-time when the load path cannot afford
  it or the region is read by more than one master.
- **The chip itself.** GX's 056734 (ESC) gets its kernel from the game ROM, decrypted with a per-chip
  key. The game then uploads programs that the kernel decrypts. MAME replaces all of it with C per
  game; the core runs the chip (`rtl/esc/k056734.sv`).
  - The per-chip constants are a table in `docs/ESC.md`, checked for every set in the driver.
    Clones carry their parent's chip.
  - Verification is a Python model of the chip (`scripts/k056734/chip.py`) against packets captured
    from MAME, then the RTL against the model (`scripts/esc_chip_check.py`).
  - Running the chip turned up differences from MAME's C, which are recorded rather than "fixed".

## Before you write any of it

- **Look for existing RTL first.** DE156's fetch-time descramble came from
  `MiSTer-devel/Arcade-Deco156Simple_Mister` (GPL-3.0); the cipher document for the 056734 is
  `konami_056734_manual.md` in `ppriest/mame-ai-tips`.
- **List the variants in HARDWARE_NOTES**, set by set: which regions, which key, which sets have no
  scramble. DecoMLC: acchi's samples are plain, and hoops swaps channels. A set with no transform
  still needs its row.
