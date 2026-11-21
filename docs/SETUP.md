# Setup: the one step only Andrew can do

Claude cannot create a GitHub repository for you. Everything else is built and tested.

## Create the empty repository (1 minute)

1. Open https://github.com/new and sign in if asked.
2. In **Repository name**, type exactly: `retail-deal-scanner`
3. Click **Private**.
4. Leave everything else as it is. Do not tick "Add a README", and leave .gitignore and license on "None".
5. Click the green **Create repository** button.
6. In the Claude chat, type: `repo created`

Claude then connects to the repository and uploads the code, the Durham test run and its ledger.

## Costs

- None. The scanner needs no paid service and no key.
- The GitHub check that runs the tests on every upload uses GitHub Actions. A private repository on GitHub Free
  includes 2,000 minutes a month, and the default spending limit is $0, so extra use is blocked rather than billed.
  One test run takes about a minute.

## Optional: a Claude Project for it

`docs/PROJECT_INSTRUCTIONS.md` holds instructions for a Project named `Software: Retail Deal Scanner`, if you want scans
to run in their own Project instead of this one.
