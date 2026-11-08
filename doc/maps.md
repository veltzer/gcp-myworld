# Maps

Museum visits and organizations each have an `address` and a `latitude`
and `longitude` (WGS 84 degrees; both or neither). With them, the Map
layout, next to List, Cards, Tiles and Gallery, shows the view on screen
as pins on an OpenStreetMap map. Two visits of the same museum share a
pin, and its popup lists both, each with a link to its edit dialog. The
search and the type filter apply to the map as they do to the cards, and
the count says how many rows have no location and so are not on it. On
the views with no places (concerts, people, the types) the Map button is
there but disabled.

The map is Leaflet, loaded from cdnjs (with its integrity hash) the
first time a map is shown, so the other layouts never load it. The tiles
come from `tile.openstreetmap.org`, under its tile usage policy: light,
interactive use with the attribution shown.

## Where the coordinates come from

`scripts/geocode.py` looks up every row that has an address but no
coordinates and saves what it finds:

```bash
scripts/with_cloud_db.sh scripts/geocode.py --dry-run   # look, save nothing
scripts/with_cloud_db.sh scripts/geocode.py             # save
```

It asks OpenStreetMap's Nominatim, one request a second as its usage
policy asks. Postcodes, floors and (remarks) are left out of the query.
An address that does not match a building is tried as the name in its
city ("Westminster Abbey, London"), then matched on its street, and then
without its first parts, down to city and country. Each line it prints
says which of these matched, so a place found only by its street or its
city is easy to spot and correct by hand in the dialog, where latitude
and longitude can be typed.

The `museum-addresses`, `museum-locations` and `organization-locations`
checks (`checks.md`) list the rows that are missing an address or
coordinates.
