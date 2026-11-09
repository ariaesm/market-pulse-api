# Contributing

Thanks for your interest in improving market-pulse-api.

1. Fork the repository and create a feature branch from `main`.
2. Install the dev environment: `pip install -e ".[dev,redis]"`.
3. Make your change. Keep pure logic (indicators, rules, cache, providers' parsing)
   free of web-framework imports so it stays easy to test.
4. Add or update tests, then run `make lint` and `make test`. Both must pass.
5. Use [Conventional Commits](https://www.conventionalcommits.org/) for commit messages
   (`feat:`, `fix:`, `docs:`, `test:`, ...).
6. Open a pull request describing the change and its motivation.

New indicators need tests against hand-computed values. Bug reports should include a
minimal reproduction (request, expected response, actual response).
