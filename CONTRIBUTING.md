## Contributing

Thanks for contributing to `adami-kernel`.

### Quick dev setup

```bash
poetry install
poetry run ruff check src/ tests/
poetry run pyright
poetry run pytest -m "not integration and not stress"
```

### License and contributions

This repository is dual-licensed (see `DUAL_LICENSE.md`). To keep the project commercially
licensable, contributions must be made under terms that allow the maintainer to distribute the
project under both:

- **AGPL-3.0-or-later** (open source), and
- a **commercial license** (proprietary).

### Contributor License Agreement (CLA) (required)

To ensure the project remains commercially licensable, **all contributions require a signed CLA**
that assigns contribution copyrights to the project owner.

- See `CLA.md`
- Contact: `erik.hwang@hotmail.com`

### Developer Certificate of Origin (DCO)

We use a DCO-style sign-off for contributions.

By contributing, you certify the statements in the DCO below and agree that your contribution may
be redistributed under the project’s dual-licensing model.

Sign your commits with:

```bash
git commit -s
```

### DCO 1.1 (text)

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I have the right to submit it under
the open source license indicated in the file; or

(b) The contribution is based upon previous work that, to the best of my knowledge, is covered
under an appropriate open source license and I have the right under that license to submit that
work with modifications, whether created in whole or in part by me, under the same open source
license (unless I am permitted to submit under a different license), as indicated in the file; or

(c) The contribution was provided directly to me by some other person who certified (a), (b) or (c)
and I have not modified it.

(d) I understand and agree that this project and the contribution are public and that a record of
the contribution (including all personal information I submit with it, including my sign-off) is
maintained indefinitely and may be redistributed consistent with this project or the open source
license(s) involved.

