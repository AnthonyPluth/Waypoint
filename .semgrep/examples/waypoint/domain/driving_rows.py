# waypoint/domain/driving_rows.py: a module that is neither driving_routes.py nor route_warming.py.
# ruleid: waypoint-driving-route-rows
rows = conn.orm.scalars(select(DrivingRoute).where(DrivingRoute.trip_id == trip_id))
# ok: waypoint-driving-route-rows
known = driving_routes.paths_for(conn, viewer, trip_id, keys, now)
