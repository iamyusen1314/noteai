# Frontend vendor assets

Runtime browser dependencies are served from the NoteAI origin. Production
HTML must not load JavaScript from a third-party CDN.

| Asset | Upstream package | License | SHA-256 |
|---|---|---|---|
| `assets/vendor/echarts-5.4.3.min.js` | `echarts@5.4.3` | Apache-2.0 | `1156429a16a38cb8604dcc6518c19406d4226142d908f8edd2e3531443c54d19` |
| `assets/vendor/lucide-1.27.0.min.js` | `lucide@1.27.0` | ISC | `e37f337f85a50b1af4c830cb46e32545201ab6625f00deacf42721bf33ff0de0` |

The corresponding upstream license texts are stored under
`assets/vendor/licenses/`. The packages were acquired from the public npm
registry without credentials. Updating either file requires an explicit
version, refreshed license/hash evidence and an offline browser regression.
