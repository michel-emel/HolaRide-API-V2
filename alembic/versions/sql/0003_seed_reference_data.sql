-- ============================================================
-- HolaRide MVP — Example Seed Data
-- Run this AFTER 001_schema.sql.
-- This gives you enough data to test trip search, pricing,
-- and cancellation logic locally before touching real data.
-- ============================================================

-- --- Cities ---
insert into cities (name) values
  ('Douala'), ('Yaoundé'), ('Bafoussam'), ('Kribi');

-- --- Locations (pickup points) ---
insert into locations (city_id, name)
select id, loc from cities, (values
  ('Deido'), ('Akwa'), ('Bonaberi'), ('Bepanda')
) as l(loc)
where cities.name = 'Douala';

insert into locations (city_id, name)
select id, loc from cities, (values
  ('Mvan'), ('Bastos'), ('Poste Centrale'), ('Ngoa-Ekelle')
) as l(loc)
where cities.name = 'Yaoundé';

-- --- Vehicle categories ---
insert into vehicle_categories (name, description) values
  ('Comfort', 'Standard comfortable sedan'),
  ('Premium', 'Higher-end vehicle, extra comfort');

-- --- Routes ---
insert into routes (origin_city_id, destination_city_id)
select d.id, y.id from cities d, cities y
where d.name = 'Douala' and y.name = 'Yaoundé';

insert into routes (origin_city_id, destination_city_id)
select y.id, b.id from cities y, cities b
where y.name = 'Yaoundé' and b.name = 'Bafoussam';

-- --- Route pricing (matches the example table in the spec) ---
insert into route_pricing (route_id, vehicle_category_id, price_per_seat)
select r.id, vc.id, 4000
from routes r
join cities o on o.id = r.origin_city_id and o.name = 'Douala'
join cities d on d.id = r.destination_city_id and d.name = 'Yaoundé'
join vehicle_categories vc on vc.name = 'Comfort';

insert into route_pricing (route_id, vehicle_category_id, price_per_seat)
select r.id, vc.id, 6000
from routes r
join cities o on o.id = r.origin_city_id and o.name = 'Douala'
join cities d on d.id = r.destination_city_id and d.name = 'Yaoundé'
join vehicle_categories vc on vc.name = 'Premium';

insert into route_pricing (route_id, vehicle_category_id, price_per_seat)
select r.id, vc.id, 5000
from routes r
join cities o on o.id = r.origin_city_id and o.name = 'Yaoundé'
join cities d on d.id = r.destination_city_id and d.name = 'Bafoussam'
join vehicle_categories vc on vc.name = 'Comfort';

insert into route_pricing (route_id, vehicle_category_id, price_per_seat)
select r.id, vc.id, 7000
from routes r
join cities o on o.id = r.origin_city_id and o.name = 'Yaoundé'
join cities d on d.id = r.destination_city_id and d.name = 'Bafoussam'
join vehicle_categories vc on vc.name = 'Premium';

-- --- Cancellation policy tiers (admin-configurable defaults) ---
insert into cancellation_policy_tiers (min_hours_before, max_hours_before, fee_percentage) values
  (24, null, 10),   -- more than 24h before departure
  (6, 24, 25),       -- 6h to 24h before departure
  (0, 6, 50);        -- less than 6h before departure

-- ============================================================
-- Quick sanity checks you can run after seeding:
--
--   select * from cities;
--   select r.id, o.name as origin, d.name as destination, vc.name as category, rp.price_per_seat
--     from route_pricing rp
--     join routes r on r.id = rp.route_id
--     join cities o on o.id = r.origin_city_id
--     join cities d on d.id = r.destination_city_id
--     join vehicle_categories vc on vc.id = rp.vehicle_category_id;
--   select * from cancellation_policy_tiers;
-- ============================================================
