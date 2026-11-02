/** Native binary transport codec. Decoded bytes never retain an arbitrary JSON envelope. */
export function decodeBase64(value: string): Uint8Array<ArrayBuffer> {
  const binary = atob(value);
  if (btoa(binary) !== value) throw new Error("BASE64_INVALID");
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}
export function encodeBase64(bytes: Uint8Array): string {
  return btoa(Array.from(bytes, (byte) => String.fromCharCode(byte)).join(""));
}
