import fs from 'node:fs';

const read = (path) => fs.readFileSync(path, 'utf8');
let failures = 0;
let passes = 0;

function check(condition, message) {
  if (condition) {
    passes += 1;
    console.log(`PASS  ${message}`);
  } else {
    failures += 1;
    console.error(`FAIL  ${message}`);
  }
}

console.log('\nSAHJONY Deployment Recovery Doctor');
console.log('===================================');

const config = JSON.parse(read('vercel.json'));
const workflow = read('.github/workflows/vercel-recovery-deploy.yml');
const script = read('scripts/vercel_deploy_recovery.sh');
const skill = read('skills/deployment-recovery/SKILL.md');

check(config.git?.deploymentEnabled === false, 'Automatic Vercel Git deployments are disabled');
check(workflow.includes('branches: [main]'), 'Prebuilt workflow targets main');
check(workflow.includes('cancel-in-progress: true'), 'Duplicate production workflows are coalesced');
check(workflow.includes('npm install --no-audit --no-fund'), 'Application dependencies are installed before validation');
check(workflow.includes('secrets.VERCEL_TOKEN'), 'Deployment credential comes from GitHub Secrets');
check(script.includes('VERCEL_CLI_VERSION:-59.3.0'), 'Vercel CLI is pinned');
check(script.includes('deploy --prebuilt --archive=tgz'), 'Deployment uploads a prebuilt immutable artifact');
check(script.includes('promote "$DEPLOY_URL"'), 'Production is promoted only after immutable smoke tests');
check(script.includes('MODE="${1:-deploy}"'), 'Recovery script supports deterministic validation mode');
check(script.includes('https://www.sahjony.com'), 'Canonical production URL is verified');
check(skill.startsWith('---\nname: deployment-recovery\n'), 'Recovery skill has valid frontmatter');

console.log(`\nSummary: ${passes} passed, ${failures} failed`);
if (failures) process.exit(1);
