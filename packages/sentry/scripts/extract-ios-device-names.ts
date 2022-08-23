/* eslint-env node */
import fs from 'fs';
import path from 'path';

import prettier from 'prettier';

// joining path of directory
const tmpOutputPath = path.join(
  __dirname,
  '../static/app/constants/ios-device-list.tmp.tsx'
);
const outputPath = path.join(__dirname, '../static/app/constants/ios-device-list.tsx');
const directoryPath = path.join(__dirname, '../../../node_modules/ios-device-list/');

async function getDefinitionFiles(): Promise<string[]> {
  const files: string[] = [];

  const maybeJSONFiles = await fs.readdirSync(directoryPath);

  // listing all files using forEach
  maybeJSONFiles.forEach(file => {
    if (!file.endsWith('.json') || file === 'package.json') {
      return;
    }

    files.push(path.join(path.resolve(directoryPath), file));
  });

  return files;
}

type Generation = string;
type Identifier = string;

type Mapping = Record<Identifier, Generation>;

async function collectDefinitions(files: string[]): Promise<Mapping> {
  const definitions: Mapping = {};

  const queue = [...files];

  while (queue.length > 0) {
    const file = queue.pop();

    if (!file) {
      throw new Error('Empty queue');
    }

    const contents = fs.readFileSync(file, 'utf-8');
    const content = JSON.parse(contents);

    if (typeof content?.[0]?.Identifier === 'undefined') {
      continue;
    }

    for (let i = 0; i < content.length; i++) {
      definitions[content[i].Identifier] = content[i].Generation;
    }
  }

  return definitions;
}

const HEADER = `
// THIS IS AN AUTOGENERATED FILE. DO NOT EDIT THIS FILE DIRECTLY.
// generated using scripts/extract-ios-device-names.ts as part of build step.
// the purpose of the script is to extract only the iOS information that Sentry cares about
// and discard the rest of the JSON so we do not end up bloating bundle size.
`;

const template = (contents: string) => {
  return `
      ${HEADER}
      const iOSDeviceMapping: Record<string, string> = ${contents}

      export {iOSDeviceMapping}
  `;
};

const formatOutput = async (unformatted: string) => {
  const config = await prettier.resolveConfig(outputPath);
  if (config) {
    return prettier.format(unformatted, {...config, parser: 'babel'});
  }

  return unformatted;
};

export async function extractIOSDeviceNames() {
  const files = await getDefinitionFiles();
  const definitions = await collectDefinitions(files);
  const formatted = await formatOutput(
    template(JSON.stringify(definitions, undefined, 2))
  );

  // All exit code has to synchronous
  const cleanup = () => {
    if (fs.existsSync(tmpOutputPath)) {
      fs.unlinkSync(tmpOutputPath);
    }
  };

  process.on('exit', cleanup);
  process.on('SIGINT', () => {
    cleanup();
    process.exit(1);
  });

  // Write to tmp output path
  fs.writeFileSync(tmpOutputPath, formatted);
  // Rename the file (atomic)
  fs.renameSync(tmpOutputPath, outputPath);
}
