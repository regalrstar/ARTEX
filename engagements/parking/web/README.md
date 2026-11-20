# Parking console

Local dashboard over the ANPR estate. Runs on `127.0.0.1:8792`.

```bash
cd ~/Developer/artex/engagements/parking/web
python3 server.py
```

## Search modes

| mode | what it does |
|---|---|
| **plate** | exact or prefix plate across a date range. No site selected = the Grand Indonesia engine + every live agent. Selecting sites narrows to those agents. |
| **person** | name / phone / email / tax code against the Euklis tenant data; then "plates" resolves that identity's plate and QR credentials. |
| **watch** | saved plates with labels, removable. |
| **feed** | newest check-ins across live sites, as a quick pulse. |

Every result row shows a thumbnail when an image exists, the WIB time, direction, site
(with a `collision` flag when one plate maps to multiple brands), gate and vehicle guess
parsed from the filename.

`export csv` dumps the current result set.

## Behaviour worth knowing

- All-site searches are slow by design: ~140 agents × days, roughly 2-4 minutes. Pick
  sites when you know where the car is.
- Images come only from the Grand Indonesia engine. Agent rows have no photo — their
  report API carries none.
- Brand/model are parsed from the engine filename and are frequently wrong or blank
  (`brand_model_color_0-0-0-0`). Never trust them without the image.
- Thumbnails are cached in `thumbs/`, which partially survives old images being purged.
- Site list and gate inventory are cached dumps (`data/`), not live; refresh with the
  Mongo queries if lots change.

## Endpoints

```
GET  /api/locations?q=      site search (cached)
GET  /api/agents            live agent ports
POST /api/search            {plate, days, ports[], prefix}
POST /api/person            {q}
POST /api/identity          {id}
GET  /api/watch  POST /api/watch  DELETE /api/watch/{plate}
GET  /api/feed
GET  /api/export
GET  /api/thumb?u=<snapshot url>
```
