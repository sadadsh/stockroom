"""stm/families.py - the four F0-F7 hand-curated, datasheet-cited family tables.

Verbatim port of legacy/tools/stm32_authority.py's FAMILY_ELECTRICAL, FAMILY_POWER,
FAMILY_NOT_5V (+ _OSC_CAVEAT_PINS), and BOOTLOADER_PINS - zero-logic data, no
computation, no wiring into any Phase 1 build code. Per INTERFACES.md section 7,
this is a Phase 1 deliverable even though nothing in Phase 1 reads it yet: Phase
3's `_five_v` (stm/authority.py) is the first consumer. Porting the data now as a
zero-risk task leaves Phase 3 no porting work.

Do NOT add _five_v, _subline_candidates, _part_draw_ma, or any other function here
- those are Phase 3's Layer B computations, not data. This module depends on
nothing beyond stdlib (`re`).
"""

from __future__ import annotations

import re

# routing-identity -> canonical destination net (confirm against the vault
# Connector Contract / Net Naming Contract). Defaults to the switch-engine map.
# NOT ported here: NET_DICT/TARGET_NET are NETDECK switch-fabric vocabulary,
# explicitly excluded from stm/ per INTERFACES.md section 6's reuse map.

# family -> {bootloader_periph: {canonical_pin_name, ...}}  (from ST AN2606).
# A socket position is tagged with a periph when one of its per-part pin names
# matches, for that part's family. Source: ST AN2606 Rev 62 (Mar 2024) system-
# memory-boot-mode per-device tables, EXHAUSTIVELY transcribed 2026-07-02 (225
# device/peripheral/pin-option rows across F0-F7); PDF saved in the vault at
# Sources/Datasheets/. Per family = the UNION of ROM-bootloader pins across its
# sub-lines and pin-options. USART1=PA9/PA10 and USB-DFU FS=PA11/PA12 are
# universal. Notable: F1 CAN2 is PB5/PB6 + PA9 VBUS-sense; F3 adds I2C3 (PA8/PB5);
# F4 adds SPI1-4 + I2C4; F7 has BOTH CAN1 (PD0/PD1) and CAN2 (PB5/PB13). Higher-
# density pins (PIx/PEx) never match on LQFP64/LQFP100. See docs/stm32-pins.md.
BOOTLOADER_PINS: dict = {
    "STM32F0": {
        "USART": {"PA2", "PA3", "PA9", "PA10", "PA14", "PA15"},
        "I2C": {"PB6", "PB7"},
        "USB-DFU": {"PA11", "PA12"},
    },
    "STM32F1": {
        "USART": {"PA9", "PA10", "PD5", "PD6"},
        "CAN": {"PB5", "PB6"},                       # F105/107 CAN2 RX=PB5, TX=PB6
        "USB-DFU": {"PA9", "PA11", "PA12"},          # PA9 = VBUS sense on F105/107
    },
    "STM32F2": {
        "USART": {"PA9", "PA10", "PB10", "PB11", "PC10", "PC11"},
        "CAN": {"PB5", "PB13"},                      # CAN2 RX=PB5, TX=PB13
        "USB-DFU": {"PA11", "PA12"},
    },
    "STM32F3": {
        "USART": {"PA2", "PA3", "PA9", "PA10", "PD5", "PD6"},
        "I2C": {"PA8", "PB5", "PB6", "PB7"},         # I2C1 PB6/7 + I2C3 PA8/PB5
        "USB-DFU": {"PA11", "PA12"},
    },
    "STM32F4": {
        "USART": {"PA2", "PA3", "PA9", "PA10", "PB10", "PB11", "PC10", "PC11", "PD5", "PD6"},
        "CAN": {"PB5", "PB13"},
        "I2C": {"PA8", "PB3", "PB4", "PB6", "PB7", "PB9", "PB10", "PB11", "PB14", "PB15", "PC9", "PF0", "PF1"},
        "SPI": {"PA4", "PA5", "PA6", "PA7", "PA15", "PB4", "PB5", "PB12", "PB13", "PB14", "PB15",
                "PC2", "PC3", "PC7", "PC10", "PC11", "PC12", "PE11", "PE12", "PE13", "PE14",
                "PI0", "PI1", "PI2", "PI3"},
        "USB-DFU": {"PA11", "PA12"},
    },
    "STM32F7": {
        "USART": {"PA9", "PA10", "PB10", "PB11", "PC10", "PC11"},
        "CAN": {"PB5", "PB13", "PD0", "PD1"},        # CAN1 PD0/PD1 + CAN2 PB5/PB13
        "I2C": {"PA8", "PB6", "PB9", "PC9", "PF0", "PF1"},
        "SPI": {"PA4", "PA5", "PA6", "PA7", "PE11", "PE12", "PE13", "PE14", "PI0", "PI1", "PI2", "PI3"},
        "USB-DFU": {"PA11", "PA12"},
    },
}

# Per-family I/O electrical limits, from the official ST datasheets fetched
# 2026-07-01 and saved to the vault Sources/Datasheets/ (Hard Rule 10; PDFs
# verified %PDF + rev). Values are datasheet absolute-max / operating limits.
#   io_ma       = per-pin I_IO abs-max (source and sink), mA
#   total_io_ma = SUM(I_IO) (or the device I_VDD/I_VSS ceiling that bounds it), mA
#   inj_ma      = per-pin I_INJ, mA (+/-; FT/5V-tolerant pins take -inj/+0 only)
#   vdd_v/vdda_v = operating range V; temp_c = ambient T_A range, industrial
#     6-suffix (-40..+85). The tool models one grade per family (it does not read
#     the ordering-part temp suffix), so 7-suffix +105 parts are NOT reflected here.
#   ft_5v       = family has 5V-tolerant (FT) I/O pins
# Per-pin I_IO = +/-25 mA and SUM(I_INJ) = +/-25 mA are uniform across STM32F0-F7.
# Full per-field citations: see docs/stm32-pins.md "I/O electrical (fetched)".
FAMILY_ELECTRICAL: dict = {
    "STM32F0": {"io_ma": 25, "total_io_ma": 80,  "metric": "sigma_io",     "sup_ma": None, "inj_ma": 5, "vdd_v": [2.0, 3.6], "vdda_v": [2.4, 3.6], "temp_c": [-40, 85], "ft_5v": True, "ds": "DS9826 Rev 6, Table 22 §6.2 p.52"},
    "STM32F1": {"io_ma": 25, "total_io_ma": 150, "metric": "supply_total", "sup_ma": 150,  "inj_ma": 5, "vdd_v": [2.0, 3.6], "vdda_v": [2.0, 3.6], "temp_c": [-40, 85], "ft_5v": True, "ds": "DS5319 Rev 20, Table 7 §5.2 p.37"},
    "STM32F2": {"io_ma": 25, "total_io_ma": 120, "metric": "supply_total", "sup_ma": 120,  "inj_ma": 5, "vdd_v": [1.8, 3.6], "vdda_v": [1.8, 3.6], "temp_c": [-40, 85], "ft_5v": True, "ds": "DS6329 Rev 18, Table 12 §6.2 p.70"},
    "STM32F3": {"io_ma": 25, "total_io_ma": 80,  "metric": "sigma_io",     "sup_ma": 160,  "inj_ma": 5, "vdd_v": [2.0, 3.6], "vdda_v": [2.0, 3.6], "temp_c": [-40, 85], "ft_5v": True, "ds": "DocID026415 Rev 5, Table 17 §6.2 p.71"},
    "STM32F4": {"io_ma": 25, "total_io_ma": 120, "metric": "sigma_io",     "sup_ma": 240,  "inj_ma": 5, "vdd_v": [1.8, 3.6], "vdda_v": [1.8, 3.6], "temp_c": [-40, 85], "ft_5v": True, "ds": "DS8626 (DocID022152) Rev 5, Table 12 §5.2 p.78"},
    "STM32F7": {"io_ma": 25, "total_io_ma": 120, "metric": "sigma_io",     "sup_ma": None, "inj_ma": 5, "vdd_v": [1.7, 3.6], "vdda_v": [1.7, 3.6], "temp_c": [-40, 85], "ft_5v": True, "ds": "DS10916 Rev 5, Table 16 §6.2 p.121"},
}
# total_io_ma = the datasheet's binding all-I/O current ceiling: the explicit
# SUM(I_IO) ("sum of all I/O + control pins") row where the DS states it
# (metric=sigma_io), else the device I_VDD/I_VSS supply total (metric=supply_total).
# sup_ma = the device I_VDD/I_VSS supply ceiling where separately stated. Verified
# 2026-07-02: every F4 sub-line has SUM(I_IO) = 120 mA (the old 240 was the F405/407
# *supply* total, mislabelled); the supply total varies by sub-line (below). The
# earlier "F401/F411 ~150 UNVERIFIED" guess is retired: 120 SUM(I_IO) / 160 supply.
F4_SUBLINE_SUPPLY_MA: dict = {   # device I_VDD/I_VSS total (mA); SUM(I_IO) = 120 for all
    "STM32F401": 160, "STM32F411": 160, "STM32F405/407": 240,
    "STM32F429": 270, "STM32F446": 240, "STM32F469": 290,
}
# Sources: DS10086 R5 (F401), DS10314 R8 (F411), DS9405 R13 (F429),
# DS10693/DocID027107 R6 (F446), DS11189 R8 (F469), DocID022152 R5 (F405/407).

# Per-family POWER / decoupling design data, from the official ST datasheets
# (fetched 2026-07-02, saved to the vault Sources/Datasheets/, cited).
#   vcap        = family needs external cap(s) on the internal 1.2V regulator output
#   vcap_value  = the required capacitor(s)
#   vbat_v / vref_v = VBAT and VREF+ operating ranges (vref None = internally VDDA)
#   decoupling  = the datasheet's recommended decoupling recipe
#   n_vdd/n_vss = digital VDD/VSS pin count on LQFP100 (None = not verifiable)
FAMILY_POWER: dict = {
    "STM32F0": {"vcap": False, "vcap_value": None, "vbat_v": [1.65, 3.6], "vref_v": None,
                "decoupling": "3x100nF (per VDD/VSS pair) + 4.7uF bulk; VDDA 10nF+1uF; VDDIO2 100nF+4.7uF",
                "n_vdd": 3, "n_vss": 4, "ds": "DS9826 Rev 6, Fig 13 p.49 / Table 24 p.53"},
    "STM32F1": {"vcap": False, "vcap_value": None, "vbat_v": [1.8, 3.6], "vref_v": [2.4, 3.6],
                "decoupling": "5x100nF (per VDD/VSS pair) + 4.7uF bulk (on VDD3); VDDA 10nF+1uF; VREF+ 10nF+1uF",
                "n_vdd": 5, "n_vss": 5, "ds": "DS5319 Rev 20, Fig 14 p.36 / Table 9 p.38"},
    "STM32F2": {"vcap": True, "vcap_value": "2x2.2uF (VCAP_1/2, ESR<2ohm)", "vbat_v": [1.65, 3.6], "vref_v": [1.8, 3.6],
                "decoupling": "100nF per VDD/VSS pair + 4.7uF bulk; VDDA 100nF+1uF; VREF+ 100nF+1uF",
                "n_vdd": 6, "n_vss": 3, "ds": "DS6329 Rev 18, sec 3.16.2 p.26 / Fig 19 p.68 / Table 16 p.73"},
    "STM32F3": {"vcap": False, "vcap_value": None, "vbat_v": [1.65, 3.6], "vref_v": [2.0, 3.6],
                "decoupling": "100nF per VDD/VSS pair + 4.7uF bulk; VDDA 10nF+1uF; VREF+ 10nF+1uF",
                "n_vdd": 4, "n_vss": 4, "ds": "DocID026415 Rev 5, Fig 12 p.69 / Table 19 p.72"},
    "STM32F4": {"vcap": True, "vcap_value": "2x2.2uF (VCAP_1/2, ESR<2ohm)", "vbat_v": [1.65, 3.6], "vref_v": [1.8, 3.6],
                "decoupling": "100nF per VDD/VSS pair + 4.7uF bulk; VDDA 10nF+1uF; VREF+ 10nF+1uF",
                "n_vdd": None, "n_vss": None, "ds": "DS8626 (DocID022152) Rev 5, sec 2.2.16 p.26 / Fig 21 p.76 / Table 16 p.81"},
    "STM32F7": {"vcap": True, "vcap_value": "2x2.2uF (VCAP_1/2, ESR<2ohm)", "vbat_v": [1.65, 3.6], "vref_v": [1.7, 3.6],
                "decoupling": "100nF per VDD/VSS pair + 4.7uF bulk; VDDA 100nF+1uF; VREF+ 100nF+1uF; VDDUSB 100nF+1uF",
                "n_vdd": 5, "n_vss": 5, "ds": "DS10916 Rev 5, sec 3.18.1 p.28 / Fig 22 p.119 / Table 20 p.125"},
}

# Per-family set of GPIOs that are NOT 5V-tolerant (I/O structure = TTa/TC, i.e.
# 3.3V-only). Every other GPIO is structurally FT (5V-tolerant in digital mode).
# From the datasheet "Pin definitions" I/O-structure column, exhaustively
# classified 2026-07-01 (each family 100% covered; cross-checked vs the cover-page
# 5V-tolerant count where given). PC14/PC15/PH0/PH1 are FT-except-in-osc-mode where
# they are FT; any FT pin loses 5V tolerance while in analog (ADC) mode.
# Sources: DS9826 R6 T14, DS5319 R20 T5, DS6329 R18 T8, DocID026415 R5 T13,
# DS8626/DocID022152 R5 T7, DS10916 R5 T10. See docs/stm32-pins.md.
FAMILY_NOT_5V: dict = {
    "STM32F0": {"PA0", "PA1", "PA2", "PA3", "PA4", "PA5", "PA6", "PA7", "PB0", "PB1",
                "PC0", "PC1", "PC2", "PC3", "PC4", "PC5", "PC13", "PC14", "PC15"},
    "STM32F1": {"PA0", "PA1", "PA2", "PA3", "PA4", "PA5", "PA6", "PA7", "PB0", "PB1", "PB5",
                "PC0", "PC1", "PC2", "PC3", "PC4", "PC5", "PC13", "PC14", "PC15"},
    "STM32F2": {"PA4", "PA5"},
    "STM32F3": {"PA0", "PA1", "PA2", "PA3", "PA4", "PA5", "PA6", "PA7", "PB0", "PB1", "PB2",
                "PB10", "PB11", "PB12", "PB13", "PB14", "PB15", "PC0", "PC1", "PC2", "PC3",
                "PC4", "PC5", "PC13", "PC14", "PC15", "PD8", "PD9", "PD10", "PD11", "PD12",
                "PD13", "PD14", "PD15", "PE7", "PE8", "PE9", "PE10", "PE11", "PE12", "PE13",
                "PE14", "PE15", "PF2", "PF4"},
    "STM32F4": {"PA4", "PA5"},
    "STM32F7": {"PA4", "PA5"},
}
_OSC_CAVEAT_PINS = {"PC14", "PC15", "PH0", "PH1"}   # FT except in oscillator mode
_GPIO_NAME = re.compile(r"^P[A-Z]\d+$")
