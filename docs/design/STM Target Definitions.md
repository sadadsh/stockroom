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
- deterministic channel allocation for routes that the policy says must be
  implemented;
- explicit blockers, warnings, and a SHA-256 digest over the whole artifact.

Any missing silicon provenance, required route, safety rule, cited evidence, or
declared channel capacity fails closed.

## Functional Foundation

The functional-foundation audit is separate from debug and communication
services. For every selected target it inventories:

- every digital supply pin;
- analog supplies;
- backup-domain supply;
- exposed voltage-reference pins;
- all digital and analog ground returns;
- VCAP and other core-regulator obligations represented by the source data;
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
| `safety_collision` | Power, ground, regulator, boot, or other critical identity conflicts | `isolate` |
| `partial` | The physical position is absent from part of the selected set | `unsupported` |

Safety rules may replace isolation with a safe action. A branch rule must:

- cite evidence;
- default open, off, or high impedance;
- cover every silicon identity exactly once;
- identify the targets matched by each branch;
- declare its net and whether it consumes a controlled channel.

Routes through a collision are usable only when the selected target is covered
by a non-isolating branch. Route selection never overrides the position's safety
action.

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
functions and does not claim a board net or channel. A required implementation
does claim its physical route and participates in conflict and capacity checks.

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

## Consumer Rules

A consumer should pin the full artifact digest and reject stale or corrupt
artifacts. It should map every promised action to a concrete schematic pin, net,
connector, or test point and keep closure open while the artifact is blocked.

Generated facts should precede hand-maintained prose. A raw compatibility union
may remain available as silicon evidence, but it must not supersede the target
definition.
