# Bundled travel logos

The catalog in `manifest.json` records each brand, its local filename, source URL and upstream Git blob SHA. SVG assets are static images with no scripts or external resources; PNGs are bundled as received, with a dark backing added to the white Regent mark so it stays visible. Brand marks remain the property of their respective owners and identify the providers of a booking or loyalty program.

Most SVGs come from [detain/svg-logos](https://github.com/detain/svg-logos), a mirror of WorldVectorLogo. Airline PNGs come from [sexym0nk3y/airline-logos](https://github.com/sexym0nk3y/airline-logos). Additional cruise SVGs come from [kaliartistry/cruisekit](https://github.com/kaliartistry/cruisekit). Hotel and additional cruise images come from the brand asset collections recorded in their entries. See each entry for its exact source.

The application reads these files from disk. It never contacts these sources at runtime. Add a reviewed static image and a manifest entry to extend coverage. Update matching aliases in `waypoint/storage/bundled_logos.py` when a provider uses another name.
