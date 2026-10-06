/** Byte-budgeted LRU for typed arrays. */
export class ByteLRU<V extends ArrayBufferView> {
  private map = new Map<string, V>();
  private bytes = 0;
  constructor(public budget: number) {}

  get(key: string): V | undefined {
    const v = this.map.get(key);
    if (v !== undefined) {
      this.map.delete(key);
      this.map.set(key, v); // refresh recency
    }
    return v;
  }
  has(key: string): boolean {
    return this.map.has(key);
  }
  set(key: string, v: V): void {
    const old = this.map.get(key);
    if (old) this.bytes -= old.byteLength;
    this.map.set(key, v);
    this.bytes += v.byteLength;
    for (const [k, val] of this.map) {
      if (this.bytes <= this.budget || this.map.size <= 1) break;
      this.map.delete(k);
      this.bytes -= val.byteLength;
    }
  }
  delete(key: string): void {
    const old = this.map.get(key);
    if (old) {
      this.bytes -= old.byteLength;
      this.map.delete(key);
    }
  }
  get size(): number {
    return this.map.size;
  }
  get byteSize(): number {
    return this.bytes;
  }
}
