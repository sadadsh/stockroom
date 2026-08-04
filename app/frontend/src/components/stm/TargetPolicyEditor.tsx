import { useEffect, useRef, useState } from "react";
import type { TargetDefinitionPolicy } from "../../api/types";
import { Text, useText } from "../../lib/copy";
import { Button, Eyebrow } from "../primitives";

const CUBEMX_EVIDENCE = "STM32CubeMX derived pin roles and alternate-function tables";

export const CORE_BRING_UP_POLICY: TargetDefinitionPolicy = {
  id: "stm32-access-audit",
  revision: 2,
  coverage_mode: "explicit-device-set",
  requirements: [
    {
      id: "nrst",
      label: "Reset",
      net: "NRST",
      required: true,
      category: "control",
      service_group: "debug-swd",
      direction: "input",
      access_plane: "function",
      purposes: ["reset", "debug", "recovery"],
      access_tags: ["reset"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "boot0",
      label: "Boot 0",
      net: "BOOT0",
      required: true,
      category: "boot",
      service_group: "boot-control",
      direction: "input",
      access_plane: "function",
      purposes: ["boot-selection", "recovery"],
      access_tags: ["boot0"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "boot1",
      label: "Boot 1",
      net: "BOOT1",
      required: false,
      category: "boot",
      service_group: "boot-control",
      direction: "input",
      access_plane: "function",
      purposes: ["boot-selection", "recovery"],
      access_tags: ["boot1"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "swdio",
      label: "SWD Data",
      net: "SWDIO",
      required: true,
      category: "debug",
      service_group: "debug-swd",
      protocol: "SWD",
      direction: "bidirectional",
      access_plane: "function",
      purposes: ["identify", "program", "debug", "data-access"],
      access_tags: ["swdio"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "swclk",
      label: "SWD Clock",
      net: "SWCLK",
      required: true,
      category: "debug",
      service_group: "debug-swd",
      protocol: "SWD",
      direction: "input",
      access_plane: "function",
      purposes: ["identify", "program", "debug", "data-access"],
      access_tags: ["swclk"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "swo",
      label: "Serial Wire Output",
      net: "SWO",
      required: false,
      category: "trace",
      service_group: "debug-swd",
      protocol: "SWV",
      direction: "output",
      access_plane: "function",
      purposes: ["trace", "observation"],
      access_tags: ["swo"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "jtag_tdi",
      label: "JTAG Data In",
      net: "JTAG_TDI",
      required: false,
      category: "debug",
      service_group: "debug-jtag",
      protocol: "JTAG",
      direction: "input",
      access_plane: "function",
      purposes: ["identify", "program", "debug", "boundary-scan"],
      signal_patterns: [".*(JTDI).*"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "jtag_tdo",
      label: "JTAG Data Out",
      net: "JTAG_TDO",
      required: false,
      category: "debug",
      service_group: "debug-jtag",
      protocol: "JTAG",
      direction: "output",
      access_plane: "function",
      purposes: ["identify", "program", "debug", "boundary-scan"],
      signal_patterns: [".*(JTDO).*"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "jtag_trst",
      label: "JTAG Reset",
      net: "JTAG_TRST",
      required: false,
      category: "debug",
      service_group: "debug-jtag",
      protocol: "JTAG",
      direction: "input",
      access_plane: "function",
      purposes: ["debug", "boundary-scan"],
      signal_patterns: [".*(NJTRST|JTRST).*"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "trace_clk",
      label: "Parallel Trace Clock",
      net: "TRACECLK",
      required: false,
      category: "trace",
      service_group: "parallel-trace",
      protocol: "ETM",
      direction: "output",
      access_plane: "function",
      purposes: ["trace", "observation"],
      signal_patterns: [".*TRACECLK.*"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "trace_d0",
      label: "Parallel Trace Data 0",
      net: "TRACED0",
      required: false,
      category: "trace",
      service_group: "parallel-trace",
      protocol: "ETM",
      direction: "output",
      access_plane: "function",
      purposes: ["trace", "observation"],
      signal_patterns: [".*TRACED0.*"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "uart_tx",
      label: "USART1 TX",
      net: "USART1_TX",
      required: false,
      category: "serial",
      service_group: "serial-uart",
      protocol: "UART",
      direction: "output",
      access_plane: "function",
      purposes: ["console", "recovery", "data-access"],
      signal_patterns: ["USART1_TX"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "uart_rx",
      label: "USART1 RX",
      net: "USART1_RX",
      required: false,
      category: "serial",
      service_group: "serial-uart",
      protocol: "UART",
      direction: "input",
      access_plane: "function",
      purposes: ["console", "recovery", "data-access"],
      signal_patterns: ["USART1_RX"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "osc_in",
      label: "High-Speed Clock In",
      net: "OSC_IN",
      required: false,
      category: "clock",
      service_group: "clock-access",
      direction: "input",
      access_plane: "function",
      purposes: ["clock-injection", "bring-up"],
      signal_patterns: ["RCC_OSC_IN", "OSC_IN"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "osc_out",
      label: "High-Speed Clock Out",
      net: "OSC_OUT",
      required: false,
      category: "clock",
      service_group: "clock-access",
      direction: "output",
      access_plane: "function",
      purposes: ["clock-observation", "bring-up"],
      signal_patterns: ["RCC_OSC_OUT", "OSC_OUT"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "usb_dp",
      label: "USB Data Positive",
      net: "USB_DP",
      required: false,
      category: "usb",
      service_group: "usb-device",
      protocol: "USB",
      direction: "bidirectional",
      access_plane: "function",
      purposes: ["communication", "recovery", "data-access"],
      signal_patterns: ["USB.*_DP", "USB_DP"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "usb_dm",
      label: "USB Data Negative",
      net: "USB_DM",
      required: false,
      category: "usb",
      service_group: "usb-device",
      protocol: "USB",
      direction: "bidirectional",
      access_plane: "function",
      purposes: ["communication", "recovery", "data-access"],
      signal_patterns: ["USB.*_DM", "USB_DM"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "can_tx",
      label: "CAN Transmit",
      net: "CAN_TX",
      required: false,
      category: "serial",
      service_group: "serial-can",
      protocol: "CAN",
      direction: "output",
      access_plane: "function",
      purposes: ["communication", "recovery", "data-access"],
      signal_patterns: ["CAN.*_TX", "FDCAN.*_TX"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "can_rx",
      label: "CAN Receive",
      net: "CAN_RX",
      required: false,
      category: "serial",
      service_group: "serial-can",
      protocol: "CAN",
      direction: "input",
      access_plane: "function",
      purposes: ["communication", "recovery", "data-access"],
      signal_patterns: ["CAN.*_RX", "FDCAN.*_RX"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "i2c_scl",
      label: "I2C Clock",
      net: "I2C_SCL",
      required: false,
      category: "serial",
      service_group: "serial-i2c",
      protocol: "I2C",
      direction: "bidirectional",
      access_plane: "function",
      purposes: ["communication", "recovery", "data-access"],
      signal_patterns: ["I2C1_SCL"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "i2c_sda",
      label: "I2C Data",
      net: "I2C_SDA",
      required: false,
      category: "serial",
      service_group: "serial-i2c",
      protocol: "I2C",
      direction: "bidirectional",
      access_plane: "function",
      purposes: ["communication", "recovery", "data-access"],
      signal_patterns: ["I2C1_SDA"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "spi_sck",
      label: "SPI Clock",
      net: "SPI_SCK",
      required: false,
      category: "serial",
      service_group: "serial-spi",
      protocol: "SPI",
      direction: "input",
      access_plane: "function",
      purposes: ["communication", "recovery", "data-access"],
      signal_patterns: ["SPI1_SCK"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "spi_miso",
      label: "SPI Controller Input",
      net: "SPI_MISO",
      required: false,
      category: "serial",
      service_group: "serial-spi",
      protocol: "SPI",
      direction: "output",
      access_plane: "function",
      purposes: ["communication", "recovery", "data-access"],
      signal_patterns: ["SPI1_MISO"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "spi_mosi",
      label: "SPI Controller Output",
      net: "SPI_MOSI",
      required: false,
      category: "serial",
      service_group: "serial-spi",
      protocol: "SPI",
      direction: "input",
      access_plane: "function",
      purposes: ["communication", "recovery", "data-access"],
      signal_patterns: ["SPI1_MOSI"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "spi_nss",
      label: "SPI Chip Select",
      net: "SPI_NSS",
      required: false,
      category: "serial",
      service_group: "serial-spi",
      protocol: "SPI",
      direction: "input",
      access_plane: "function",
      purposes: ["communication", "recovery", "data-access"],
      signal_patterns: ["SPI1_NSS"],
      evidence: [CUBEMX_EVIDENCE],
    },
  ],
  service_groups: [
    {
      id: "debug-swd",
      label: "SWD Debug and Identification",
      category: "debug",
      protocol: "SWD",
      required: true,
      claim_scope: "pin-capability",
      purposes: ["identify", "program", "debug", "data-access"],
      requirement_ids: ["nrst", "swdio", "swclk", "swo"],
      required_requirement_ids: ["swdio", "swclk"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "boot-control",
      label: "Reset and Boot Selection",
      category: "boot",
      required: true,
      claim_scope: "pin-capability",
      purposes: ["boot-selection", "recovery"],
      requirement_ids: ["nrst", "boot0", "boot1"],
      required_requirement_ids: ["nrst", "boot0"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "debug-jtag",
      label: "JTAG Debug and Boundary Scan",
      category: "debug",
      protocol: "JTAG",
      required: false,
      claim_scope: "pin-capability",
      purposes: ["identify", "program", "debug", "boundary-scan"],
      requirement_ids: ["swdio", "swclk", "jtag_tdi", "jtag_tdo", "jtag_trst"],
      required_requirement_ids: ["swdio", "swclk", "jtag_tdi", "jtag_tdo"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "parallel-trace",
      label: "Parallel Trace",
      category: "trace",
      protocol: "ETM",
      required: false,
      claim_scope: "pin-capability",
      purposes: ["trace", "observation"],
      requirement_ids: ["trace_clk", "trace_d0"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "clock-access",
      label: "External Clock Access",
      category: "clock",
      required: false,
      claim_scope: "pin-capability",
      purposes: ["clock-injection", "clock-observation", "bring-up"],
      requirement_ids: ["osc_in", "osc_out"],
      required_requirement_ids: ["osc_in"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "serial-uart",
      label: "UART Access",
      category: "serial",
      protocol: "UART",
      required: false,
      claim_scope: "pin-capability",
      purposes: ["console", "recovery", "data-access"],
      requirement_ids: ["uart_tx", "uart_rx"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "usb-device",
      label: "USB Device Access",
      category: "usb",
      protocol: "USB",
      required: false,
      claim_scope: "pin-capability",
      purposes: ["communication", "recovery", "data-access"],
      requirement_ids: ["usb_dp", "usb_dm"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "serial-can",
      label: "CAN Access",
      category: "serial",
      protocol: "CAN",
      required: false,
      claim_scope: "pin-capability",
      purposes: ["communication", "recovery", "data-access"],
      requirement_ids: ["can_tx", "can_rx"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "serial-i2c",
      label: "I2C Access",
      category: "serial",
      protocol: "I2C",
      required: false,
      claim_scope: "pin-capability",
      purposes: ["communication", "recovery", "data-access"],
      requirement_ids: ["i2c_scl", "i2c_sda"],
      evidence: [CUBEMX_EVIDENCE],
    },
    {
      id: "serial-spi",
      label: "SPI Access",
      category: "serial",
      protocol: "SPI",
      required: false,
      claim_scope: "pin-capability",
      purposes: ["communication", "recovery", "data-access"],
      requirement_ids: ["spi_sck", "spi_miso", "spi_mosi", "spi_nss"],
      evidence: [CUBEMX_EVIDENCE],
    },
  ],
  safety_rules: [],
  routing_constraints: {
    safe_default: "open",
  },
  declared_blockers: [],
};

export function cloneCoreBringUpPolicy(): TargetDefinitionPolicy {
  return JSON.parse(JSON.stringify(CORE_BRING_UP_POLICY)) as TargetDefinitionPolicy;
}

export function TargetPolicyEditor({
  policy,
  onPolicyChange,
}: {
  policy: TargetDefinitionPolicy;
  onPolicyChange: (policy: TargetDefinitionPolicy) => void;
}) {
  const [draft, setDraft] = useState(() => JSON.stringify(policy, null, 2));
  const [error, setError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const draftLabel = useText(
    "stm.target.policy.draft.aria",
    "Target Definition Policy JSON",
  );

  useEffect(() => {
    setDraft(JSON.stringify(policy, null, 2));
    setError("");
  }, [policy]);

  const apply = () => {
    try {
      const parsed = JSON.parse(draft) as TargetDefinitionPolicy;
      if (!parsed || typeof parsed !== "object" || !parsed.id) {
        throw new Error("Policy needs a non-empty id.");
      }
      if (!Array.isArray(parsed.requirements) || !Array.isArray(parsed.safety_rules)) {
        throw new Error("Policy needs requirements and safety_rules arrays.");
      }
      onPolicyChange(parsed);
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Policy JSON is invalid.");
    }
  };

  const loadFile = async (file: File | undefined) => {
    if (!file) return;
    const text = await file.text();
    setDraft(text);
    setError("");
  };

  return (
    <details className="rounded-card border border-line bg-surface">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3">
        <span>
          <Eyebrow>
            <Text id="stm.target.policy.title">Definition Policy</Text>
          </Eyebrow>
          <span className="mt-0.5 block font-mono text-xs text-t1">{policy.id}</span>
        </span>
        <span className="text-2xs text-t3">
          <Text id="stm.target.policy.edit-json">Edit JSON</Text>
        </span>
      </summary>
      <div className="border-t border-line px-4 pb-4 pt-3">
        <p className="mb-3 text-xs text-t3">
          <Text id="stm.target.policy.explanation">
            The compiler always inventories the functional power, ground, regulator, reset, boot,
            clock, and reserved-pin foundation. This policy adds access services, required routes,
            target applicability, safety handling, and implementation-neutral routing requirements.
            Stockroom specifies connection behavior and safe states, while the consuming design
            chooses the switching, selection, or isolation technology. Pin capability stays
            distinct from externally evidenced recovery or data-access support, and the whole policy
            is included in the artifact digest.
          </Text>
        </p>
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          aria-label={draftLabel}
          spellCheck={false}
          className="h-64 w-full resize-y rounded-control bg-field p-3 font-mono text-xs text-t1 outline-none focus:ring-1 focus:ring-acc"
        />
        {error ? <p className="mt-2 text-xs text-err">{error}</p> : null}
        <div className="mt-3 flex flex-wrap gap-2">
          <Button small onClick={apply}>
            <Text id="stm.target.policy.apply">Apply Policy</Text>
          </Button>
          <Button small onClick={() => fileInput.current?.click()}>
            <Text id="stm.target.policy.load-json">Load JSON</Text>
          </Button>
          <Button
            small
            onClick={() => {
              const reset = cloneCoreBringUpPolicy();
              setDraft(JSON.stringify(reset, null, 2));
              onPolicyChange(reset);
            }}
          >
            <Text id="stm.target.policy.reset">Reset Access Profile</Text>
          </Button>
          <input
            ref={fileInput}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={(event) => void loadFile(event.target.files?.[0])}
          />
        </div>
      </div>
    </details>
  );
}
