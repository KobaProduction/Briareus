import sharp from 'sharp';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

let input = '';
for await (const chunk of process.stdin) input += chunk;
const { png: settings, jobs, base } = JSON.parse(input);
const { maxBytes, sizes, colors } = settings;
if (!Number.isInteger(maxBytes) || maxBytes < 1 || !sizes?.length || !colors?.length ||
    sizes.some(n => !Number.isInteger(n) || n < 1 || n > 4096) ||
    colors.some(n => !Number.isInteger(n) || n < 2 || n > 256)) {
  throw new Error('Invalid PNG settings: positive maxBytes, sizes 1..4096, colors 2..256 required');
}
const entries = [];
for (const job of jobs) {
  const source = await readFile(job.svg);
  let result;
  for (const size of [...new Set(sizes)].sort((a, b) => b - a)) {
    const pixels = await sharp(source, { density: 96 }).resize(size, size, {
      fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 }
    }).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
    for (const count of [...new Set(colors)].sort((a, b) => b - a)) {
      const buffer = await sharp(pixels.data, { raw: pixels.info }).png({
        palette: true, colours: count, dither: 0, compressionLevel: 9, effort: 7
      }).toBuffer();
      if (buffer.length <= maxBytes) {
        result = { buffer, size, colors: count };
        break;
      }
    }
    if (result) break;
  }
  if (!result) throw new Error(`${job.svg}: cannot fit PNG into ${maxBytes} bytes; add smaller sizes or fewer colors`);
  await writeFile(job.png, result.buffer);
  entries.push({ svg: path.relative(base, job.svg).replaceAll('\\', '/'),
    png: path.relative(base, job.png).replaceAll('\\', '/'),
    width: result.size, height: result.size, bytes: result.buffer.length,
    paletteColors: result.colors });
  console.log(`${path.basename(job.png)}: ${result.size}x${result.size}, ${result.buffer.length} bytes`);
}
console.log(`Built ${entries.length} PNGs, each <= ${maxBytes} bytes.`);
