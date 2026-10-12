// Validate one SQ-64 emulator UI script file with the emulator's own
// validator. SQ64_EMULATOR_WEB must point at the emulator checkout's web/
// directory. Prints the validated script's name as JSON on success.
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

const web = process.env.SQ64_EMULATOR_WEB;
const file = process.argv[2];
if (!web || !file) {
  console.error('usage: SQ64_EMULATOR_WEB=<emulator>/web node validate_ui_script.mjs <script.json>');
  process.exit(2);
}
try {
  const { parseScript } = await import(pathToFileURL(`${web}/emulator/scripts.js`));
  const script = parseScript(await readFile(file, 'utf8'));
  console.log(JSON.stringify({ name: script.name, actions: script.actions.length }));
} catch (error) {
  console.log(error.message);
  process.exit(1);
}
