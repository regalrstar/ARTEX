# B27 — report

Source: district8 LPR engine (Grand Indonesia), anonymous history + snapshots.
Coverage: 2026-07-18 → 2026-11-15 (380 days scanned of 470 retained). Prefix `B27`, exact plate `B27` isolated below.

Prefix universe: 46,050 events across 7,191 distinct plates.

## Exact plate `B27`

28 deduplicated events, 14 entries / 14 exits.

| in (WIB) | out (WIB) | duration | in gate | out gate | image |
|---|---|---|---|---|---|
| 2026-07-23 01:02 | 2026-07-24 00:21 | 23h19m | GDBM3 | LGBK2 | gone |
| 2026-08-05 21:49 | 2026-08-06 01:15 | 3h26m | GDBM3 | GBBK1 | gone |
| 2026-08-06 00:15 | 2026-08-07 01:37 | 25h21m | GDBM3 | GBBK1 | gone |
| 2026-08-06 01:01 | 2026-08-07 04:34 | 27h33m | GDBM3 | GBBK1 | gone |
| 2026-08-13 04:02 | 2026-08-14 03:31 | 23h29m | GEBM1 | GBBK1 | gone |
| 2026-08-14 01:23 | 2026-08-14 04:14 | 2h50m | GDBM3 | GFBK1 | gone |
| 2026-08-14 01:30 | 2026-08-15 02:46 | 25h16m | GDBM1-REV | GBBK1 | gone |
| 2026-09-30 01:35 | 2026-10-01 02:04 | 24h29m | GCBM1 | LGBK1 | [jpg](https://district8.lpr-capture.alfabeta.co.id/snapshot/GCBM1_B27_Mini_Cooper_white-silver_139-5-707-514_2026-09-29T18:35:01.jpg) |
| 2026-10-02 19:37 | 2026-10-03 01:14 | 5h37m | GDBM3 | GGBK1 | [jpg](https://district8.lpr-capture.alfabeta.co.id/snapshot/GDBM3_B27_brand_model_color_0-0-0-0_2026-10-02T12:37:47.jpg) |
| 2026-10-15 00:02 | 2026-10-15 04:31 | 4h29m | GDBM2 | GBBK1 | [jpg](https://district8.lpr-capture.alfabeta.co.id/snapshot/GDBM2_B27_Lamborghini_Aventador_red_3-7-181-220_2026-10-14T17:02:23.jpg) |
| 2026-10-16 00:19 | 2026-10-16 03:33 | 3h14m | GDBM3 | GBBK1 | [jpg](https://district8.lpr-capture.alfabeta.co.id/snapshot/GDBM3_B27_Daihatsu_Sigra_black_278-14-918-483_2026-10-15T17:19:04.jpg) |
| 2026-10-21 00:18 | 2026-10-21 06:21 | 6h02m | GDBM3 | GBBK2 | gone |
| 2026-10-29 00:57 | 2026-10-29 02:12 | 1h15m | GDBM2 | GBBK1 | [jpg](https://district8.lpr-capture.alfabeta.co.id/snapshot/GDBM2_B27_Lada_Vesta_blue_180-6-939-641_2026-10-28T17:57:29.jpg) |
| 2026-10-31 01:33 | 2026-10-31 05:40 | 4h06m | GDBM2 | GBBK1 | [jpg](https://district8.lpr-capture.alfabeta.co.id/snapshot/GDBM2_B27_Peugeot_3008_black_196-10-911-642_2026-10-30T18:33:29.jpg) |


## Reading the data

Pattern: entries almost always between **00:00 and 04:00**, exits between **01:00 and 04:34**,
at two ramps only (`GDBM2`/`GDBM3`/`GEBM1`) and the same exit barriers. Stays are long —
3 h 26 m up to 27 h 33 m — and dates cluster in late July and mid-August 2026. That is an
overnight/long-stay vehicle, not a shopper.

## Images

**All frames for this plate are purged.** The engine keeps roughly the last month of
snapshots; anything older 404s even though the row survives. Rows are therefore the durable
record, images are ephemeral — grab them the same day if they matter.

## Caveats

- Duplicate rows existed at day-window boundaries; the table is deduplicated on
  (timestamp, direction, gate).
- `B27` is not unique per car: other brands appear under the same plate in different
  periods (Peugeot 3008, Lada Vesta, Daihatsu Sigra, Lamborghini). Brand/model are not
  fields in this feed except inside the image filename, so they cannot be filtered here.
- 380 of 470 retained days scanned; July 2026 and earlier are partially covered.
