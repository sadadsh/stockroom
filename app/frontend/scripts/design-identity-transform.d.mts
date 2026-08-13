export function generatedDesignId(
  relativeFile: string,
  component: string,
  tag: string,
  line: number,
  column: number,
): string;

export function transformStockroomJsx(code: string, filename: string): Promise<string | null>;

export function stockroomDesignIdentityPlugin(): {
  name: string;
  enforce: "pre";
  transform(code: string, id: string): Promise<{ code: string; map: unknown } | null>;
};
