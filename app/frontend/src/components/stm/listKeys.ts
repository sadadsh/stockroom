/**
 * Stable React keys for the two STM lists whose rows carry NO provably unique field.
 *
 * Most STM lists key on a field the schema guarantees: pin_alternate_function is
 * UNIQUE(mcu_package_pin_id, af_index, signal), pin_role is UNIQUE(mcu_package_pin_id, role_name),
 * a union position is a dict key, and a part ref is the union's own identity. Two lists have no
 * such guarantee:
 * - pin_function rows (signal + io_modes) carry no unique constraint at all.
 * - signal candidates are (position, af_index, canonical_pin_name), and mcu_package_pin is only
 *   UNIQUE(mcu_id, physical_pin_number, raw_pin_name) - raw_pin_name is not in the DTO, so two
 *   PINREMAP identities at one position can collide on every field the row does carry.
 *
 * An array index is the wrong answer for both: it reassigns React state across rows the moment the
 * list reorders or filters. So key on the row's own content instead, and give a byte-identical
 * repeat an occurrence suffix. Distinct rows then keep their key across a reorder, and rows that
 * ARE identical are interchangeable, so which one takes "#1" cannot be observed.
 */

// One { key, item } pair per row, in the input order. `identity` returns the row's content string.
export function withStableKeys<T>(
  items: readonly T[],
  identity: (item: T) => string,
): { key: string; item: T }[] {
  const seen = new Map<string, number>();
  return items.map((item) => {
    const id = identity(item);
    const seenBefore = seen.get(id) ?? 0;
    seen.set(id, seenBefore + 1);
    return { key: seenBefore === 0 ? id : `${id}#${seenBefore}`, item };
  });
}
