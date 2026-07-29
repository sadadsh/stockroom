# STM Target Definitions

## Purpose

The STM workspace turns STM32CubeMX device descriptions into auditable hardware
facts. It has three distinct surfaces:

1. **Explorer** answers what one indexed device exposes: package pins, electrical
   classes, roles, functions, alternate functions, and source provenance.
2. **Compatibility evidence** compares an explicit device set. It shows shared,
   divergent, and partial silicon capabilities, but does not decide how a board
   should be wired.
3. **Target definition** combines the indexed facts with an explicit policy and
   emits a deterministic, content-addressed build artifact.

Capability similarity is not a wiring plan. Alternate-function differences on
the same GPIO do not create switches, and a matching peripheral signal does not
prove a bootloader, debug-unlock, recovery, or extraction procedure.

## Compiler Contract

The target-definition compiler is pure. It reads the derived STM index, accepts
an explicit target set plus policy, and returns JSON. It owns no consumer paths,
file writes, board names, connector names, or component choices.

The compiled artifact contains:

- the exact resolved device-description set and one physical package;
- source, classifier, alternate-function, geometry, policy, and compiler
  revisions;
- one record per physical package position with every per-target identity;
- functional-foundation obligations;
- grouped access services and every alternate pin candidate;
- required physical routes and whether they are direct, switched, partial,
  unavailable, or blocked;
- target-specific safety branches for critical identity collisions;
- one implementation-neutral universalization strategy per package position,
  including safe state, target-specific identity branches, generic routing-path
  counts, and downstream electrical constraints;
- explicit blockers, warnings, and a SHA-256 digest over the whole artifact.

Any missing silicon provenance, required route, safety rule, or cited evidence
fails closed. Stockroom does not require a switch, selector, relay, jumper, or
buffer part number. A consuming design may optionally declare a capacity limit,
but implementation technology is outside the compiler contract.

## Functional Foundation

The functional-foundation audit is separate from debug and communication
services. For every selected target it inventories:

- every digital supply pin;
- analog supplies;
- backup-domain supply;
- exposed voltage-reference pins;
- all digital and analog ground returns;
- VCAP and other core-regulator obligations represented by the source data;
- every remaining special supply or power/regulator control, including USB and
  secondary I/O domains as well as PDR_ON, nPOR, BYPASS_REG, and VDD12DSI;
- reset;
- boot-configuration pins;
- high-speed and low-speed external-clock pins;
- reserved and no-connect pins.

The artifact reports the exact physical positions, target applicability, board
action, and unresolved targets for each obligation. A position is not considered
safe merely because some selected targets use it as a supply or return. If
another selected target assigns a different critical identity at that position,
the position remains isolated until an evidenced safety policy covers every
identity.

CubeMX establishes pin identity. It does not establish voltage limits, capacitor
values, regulator networks, strap levels, sequencing, or permissible loading.
Those values require exact target documentation and remain an explicit consumer
obligation.

## Physical Continuity

Each package position has one silicon class and one compiled board action.

| Silicon class | Meaning | Default action |
|---|---|---|
| `fixed_critical` | One critical identity on every target | `hardwire`, except no-connect pins |
| `stable_io` | The same GPIO identity on every target | `breakout` |
| `variant_io` | GPIO identity varies, without a critical collision | `breakout` |
| `safety_collision` | Power, ground, regulator, boot, or other critical identity conflicts | `selectable` |
| `partial` | The physical position is absent from part of the selected set | `unsupported` |

Every collision receives a generic routing-adaptation strategy. Compiler
revision 8 first compacts identities that share one physical copper node:

- GPIO identities are one firmware-mapped signal path, not one path per MCU
  pin name.
- A GPIO-versus-critical-role collision prefers one passive-conditioned common
  signal path plus selectable branches only for the power, ground, regulator,
  reset, boot, or other critical roles.
- No-connect obligations and critical-versus-critical collisions remain fully
  exclusive.
- Every compact hybrid includes the fully exclusive topology as a conservative
  fallback.
- Every independent path is identified without a component, reference
  designator, device index, channel number, or register-bit assignment.

The compact hybrid is a candidate, not an electrical approval. The consuming
design must prove that the common passive path cannot source, sink, clamp, or
back-power the critical pin and must calculate impedance against voltage,
current, leakage, injection-current, edge-rate, and bandwidth limits. If that
proof fails, the compiler-provided fully exclusive fallback applies.

Safety rules turn suggested branches into evidenced branches. A branch rule
must:

- cite evidence;
- default open, off, or high impedance;
- cover every silicon identity exactly once;
- identify the targets matched by each branch;
- declare its requested net and whether it requires an independent conductive
  path.

Routes through a collision are usable only when the selected target is covered
by a non-isolating branch. Route selection never overrides the position's safety
action. The consuming design chooses the circuit technology and must validate
voltage, current, leakage, bandwidth, charge injection, power-off behavior,
break-before-make behavior, and any special power/ground/VCAP restrictions.
The artifact also carries a structured safe-state contract: unknown target,
controller startup, reset, and power loss keep all independent paths open;
target changes open before reconfiguration; identity mismatch refuses
activation; and only target-permitted paths may conduct after configuration.

## Interactive Presentation

The package remains the focal object. Five map lenses answer distinct engineering
questions without changing the selected physical position:

- **Compatibility** is an exclusive distribution of same identity, varying
  GPIO, missing position, and electrical conflict. Its percentages total 100%.
- **Run Critical** is overlapping coverage for digital, analog, backup,
  reference, and special supplies; returns; regulator pins; reset; boot; HSE;
  LSE; and reserved/no-connect obligations.
- **Electrical Role** is overlapping coverage for normalized electrical
  domains. A conflict outline remains visible while a role filter shows the
  underlying power, ground, regulator, control, or I/O population.
- **Service Access** exposes SWDIO, SWCLK, SWO, JTAG, parallel trace, reset,
  BOOT0, BOOT1, HSE, LSE, USB, UART/USART, CAN/FDCAN, I2C, SPI, analog, and
  policy-selected routes independently.
- **Routing Plan** is an exclusive distribution of direct/fixed, compact
  hybrid, fully exclusive, policy-defined, and excluded topologies.

Every visible legend category shows a position count and percentage and filters
the package. The complete legend guide retains zero-count categories, definitions,
measurement basis, and grouped navigation so absence remains explicit. Exclusive
lenses use one category per position; overlapping lenses state their denominator
and do not imply that percentages should total 100%.

After a family target compiles, the Bench remains a fixed workstation rather
than becoming a report page. Package selection is the next action after family
scope and therefore moves above the internally scrolling family list. The
package map owns the dominant center stage; its lens guidance and active
categories stay in one compact strip. A selected position opens a bounded
inspector with three views:

- **Decision** states the electrical consequence, required board action,
  routing cost, safe default, universal strategy, branches, and immediate
  obligations.
- **MCUs** groups exact targets by canonical pin and electrical identity with
  honest denominators and expandable device references.
- **Evidence** keeps run-critical coverage, access routes, safety branches,
  routing paths, fallback topology, and validation constraints available
  without extending the page.

The page itself never scrolls. Families, packages, the selected-position view,
and opened evidence drawers own their overflow independently.

## Access Services

Signals are grouped by usable service rather than displayed as an undifferentiated
alternate-function list. Policies can describe:

- SWD reset, clock, data, identification, programming, and debug;
- SWO and serial-wire trace;
- JTAG and boundary scan;
- parallel trace;
- boot straps;
- external clock injection and observation;
- UART, USB, CAN, I2C, and SPI access;
- other target-specific services expressed with signal patterns and
  applicability filters.

Each requirement records direction, protocol, purpose, target applicability,
selected route, all alternate candidates, physical implementation commitment,
usable coverage, and evidence.

`implementation_required` is the boundary between an audit and a circuit
promise. A capability-only requirement may share a GPIO with other alternate
functions and does not claim a board net or independent path. A required implementation
does claim its physical route and participates in conflict and independent-path
checks.

## Debug, Recovery, And Extraction Claims

The evidence level is explicit:

- `pin-capability` means only that indexed pin data exposes the signal.
- `documented-service` means an external, target-applicable source establishes
  the silicon service.
- `validated-procedure` means a cited procedure has been validated and has
  procedure references.

Sensitive services may also declare entry conditions, protection constraints,
side effects, whether the path is destructive, and procedure references.

A pin-capability result must never be presented as proof of:

- ROM bootloader availability;
- the peripheral instance or pin mapping used by a ROM bootloader;
- access while readout protection or debug authentication is active;
- non-destructive memory extraction;
- option-byte behavior;
- a working tool or bench procedure.

Those claims require an exact target scope and external evidence. The viewer
keeps them visible as unproven when only pin data is available.

## Handoff Exports

The Bench exports four generic handoff files from the compiled target currently
on screen:

- **Rebuild Request** is a `stm-target-request/2` JSON document with the exact
  resolved device refs and complete caller-owned policy. Re-running it cannot
  silently add devices from a wider family/package query.
- **Target Definition** is the complete `stm-target-definition/2` authority,
  including candidates, evidence, readiness, provenance, the universalization
  strategy for every position, and artifact digest.
- **Physical Pin Plan** is a UTF-8 CSV with one row per physical package
  position. It includes target-specific identities, electrical classes, MPN
  status, signals, foundation obligations, safety branches, routes, generic
  active and passive routing paths, universal primitives, connection modes,
  conservative fallbacks, selection rules, structured validation checks,
  failure actions, and the global safe-state contract.
- **Access Route Plan** is a UTF-8 CSV with one row per requirement and selected
  target. It keeps capability authority, applicability, selected route,
  alternate candidates, protection constraints, side effects, and procedure
  evidence together.

Both schedules repeat the artifact and policy digests. Their
`implementation_*` columns are intentionally blank: the consuming design must
name its actual symbol pin or pad, net, connector or test point, evidence, and
verification state. Stockroom does not invent those consumer-owned facts.

The Stockroom contract ends at generic silicon evidence, topology requirements,
proof obligations, and safe behavior. EDA system, project, card, component,
reference designator, channel packing, and firmware register assignments are
downstream concerns and are not valid target-definition policy.

## Consumer Rules

A consumer should pin the full artifact digest and reject stale or corrupt
artifacts. It should map every promised action to a concrete schematic pin, net,
connector, or test point and keep closure open while the artifact is blocked.

Generated facts should precede hand-maintained prose. A raw compatibility union
may remain available as silicon evidence, but it must not supersede the target
definition.
