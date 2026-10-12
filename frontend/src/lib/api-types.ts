export interface AiBody {
  mode: "off" | "local" | "openrouter";
  ollama_url?: string;
  ollama_model?: string;
  openrouter_model?: string;
  openrouter_key?: string;
}

export interface AiSettings {
  mode: "off" | "local" | "openrouter";
  ollama_url: string;
  ollama_model: string;
  openrouter_model: string;
  key: "env" | "saved" | null;
}

export interface AiSuggestion {
  kind: "flight" | "hotel" | "car" | "train" | "cruise" | "parking";
  origin: string;
  start_local: string;
  end_local: string;
  provider?: string;
  confirmation?: string;
  destination?: string;
  start_zone?: string;
  end_zone?: string;
  address?: string;
  phone?: string;
  room?: string;
  ship?: string;
  deck?: string;
  flight_number?: string;
  cabin?: string;
  price_minor?: number;
  price_currency?: string;
  sources?: Record<string, string>;
}

export interface Airport {
  code: string;
  name: string;
  city: string;
  country: string;
  zone: string;
}

export interface AssistantCandidate {
  segment_id: number;
  trip_id: number;
  trip_name: string;
  kind: string;
  provider: string | null;
  origin: string | null;
  destination: string | null;
  start_local: string;
  end_local: string;
  confidence: "exact" | "likely" | "possible";
  agreed: string[];
  differed: string[];
}

export interface AssistantCreateBody {
  kind?: "flight" | "hotel" | "car" | "train" | "cruise" | "parking";
  status?: "confirmed" | "changed" | "cancelled";
  confirmation?: string | null;
  provider?: string | null;
  start_local?: string;
  start_zone?: string | null;
  end_local?: string;
  end_zone?: string | null;
  origin?: string | null;
  destination?: string | null;
  details?: Record<string, string>;
  manage_url?: string | null;
  travelers?: TravelerBody[];
  itinerary?: Port[];
  price?: PriceBody | null;
  entry?: number | null;
}

export interface AssistantDismissBody {
  reason: "not_travel" | "duplicate" | "already_added" | "other";
  note?: string | null;
}

export interface AssistantDismissed {
  ok: boolean;
  reason: "not_travel" | "duplicate" | "already_added" | "other";
}

export interface AssistantEmail {
  subject: string | null;
  sender_domain: string | null;
  received: string | null;
  text: string;
  truncated: boolean;
  html: string | null;
  html_truncated: boolean;
  kept: "original" | "plain text";
}

export interface AssistantEntry {
  entry: number;
  booking: AssistantParsed;
  candidates: AssistantCandidate[];
}

export interface AssistantItem {
  id: number;
  mailbox_id: number;
  mine: boolean;
  sender_domain: string;
  reason: "no_markup" | "incomplete" | "broken" | "match" | "generic";
  status: string | null;
  kind: string | null;
  received: string | null;
  has_email: boolean;
  bookings: number;
  match: AssistantMatch | null;
}

export interface AssistantItemDetail {
  id: number;
  mailbox_id: number;
  mine: boolean;
  sender_domain: string;
  reason: "no_markup" | "incomplete" | "broken" | "match" | "generic";
  status: string | null;
  kind: string | null;
  received: string | null;
  has_email: boolean;
  bookings: number;
  match: AssistantMatch | null;
  entries: AssistantEntry[];
  suggestion: AssistantParsed | null;
  suggestions: AssistantParsed[];
}

export interface AssistantItems {
  items: AssistantItem[];
  total: number;
  not_shown: number;
  next: string | null;
}

export interface AssistantMatch {
  segment_id: number;
  trip_id: number;
  confidence: "exact" | "likely" | "possible";
}

export interface AssistantMatchBody {
  entry?: number | null;
  segment_id?: number | null;
  trip_id?: number | null;
}

export interface AssistantMatched {
  ok: boolean;
  segment_id: number;
  trip_id: number;
}

export interface AssistantParsed {
  kind: string | null;
  status: string | null;
  provider: string | null;
  confirmation: string | null;
  origin: string | null;
  destination: string | null;
  address: string | null;
  phone: string | null;
  start_local: string | null;
  start_zone: string | null;
  end_local: string | null;
  end_zone: string | null;
  details: Record<string, string>;
  travelers: string[];
  read: Record<string, string>;
}

export interface AssistantSegmentEmails {
  emails: AssistantEmail[];
}

export interface Attached {
  ok: boolean;
  segment_id: number;
}

export interface BackupContents {
  created: string | null;
  source: string | null;
  counts: Record<string, number>;
  current: Record<string, number>;
  database: "sqlite" | "postgres";
}

export interface ClaimSuggestions {
  guests: Person[];
}

export interface CostTotal {
  currency: string;
  amount_minor: number;
}

export interface CruiseDay {
  day: number;
  date: string;
  sea: boolean;
  stops: CruiseStop[];
}

export interface CruiseStop {
  name: string;
  zone: string;
  arrive_local: string | null;
  depart_local: string | null;
  recorded: boolean;
}

export interface DestinationSuggestion {
  suggestion: string;
}

export interface DeviceBody {
  endpoint: string;
  p256dh: string;
  auth: string;
}

export interface Disconnected {
  ok: boolean;
  revoked: boolean;
}

export interface DistanceUnit {
  distance_unit: "mi" | "km";
}

export interface DistanceUnitBody {
  distance_unit: "mi" | "km";
}

export interface EmailsCleared {
  removed: number;
}

export interface FeedMade {
  url: string;
}

export interface FlightStatus {
  segment_id: number;
  state: "scheduled" | "delayed" | "departed" | "landed" | "cancelled" | "diverted";
  origin: string | null;
  destination: string | null;
  dep_scheduled: string | null;
  dep_estimated: string | null;
  dep_actual: string | null;
  dep_zone: string;
  dep_terminal: string | null;
  dep_gate: string | null;
  arr_scheduled: string | null;
  arr_estimated: string | null;
  arr_actual: string | null;
  arr_zone: string;
  arr_terminal: string | null;
  arr_gate: string | null;
  delay_minutes: number | null;
  fetched_at: string;
}

export interface FlightStatusList {
  enabled: boolean;
  month: string;
  used: number;
  limit: number;
  paused: FlightStatusPause | null;
  statuses: FlightStatus[];
}

export interface FlightStatusPause {
  until: string;
  reason: "limit" | "rate" | "key";
}

export interface GateCode {
  state: "ready" | "choose";
  day: string | null;
}

export interface GateCodeBody {
  email: number;
  image: number;
}

export interface GlanceDomain {
  domain: string;
  count: number;
  reason: "no_markup" | "incomplete" | "broken" | "match" | "generic";
  item_id: number | null;
  known_sender: boolean;
}

export interface GlanceGap {
  label: string;
  count: number;
}

export interface GlanceReason {
  reason: "no_markup" | "incomplete" | "broken" | "match" | "generic";
  waiting: number;
  recent: number;
}

export interface GlanceScan {
  at: string;
  added: number;
}

export interface IgnoredSenders {
  domains: string[];
}

export interface Ignoring {
  ok: boolean;
  mailbox_id: number;
  domain: string;
}

export interface ImportBody {
  flights: ImportFlight[];
  person_ids?: number[];
}

export interface ImportFlight {
  day: string;
  origin: string;
  destination: string;
  flight_number?: string | null;
  airline?: string | null;
  start_local?: string | null;
  end_local?: string | null;
  seat?: string | null;
  cabin?: string | null;
  aircraft?: string | null;
}

export interface ImportPreview {
  format: string;
  me: number | null;
  rows: ImportRow[];
}

export interface ImportRow {
  line: number;
  status: "new" | "exists" | "unreadable";
  reason: string | null;
  day: string | null;
  origin: string | null;
  destination: string | null;
  flight_number: string | null;
  airline: string | null;
  start_local: string | null;
  end_local: string | null;
  seat: string | null;
  cabin: string | null;
  aircraft: string | null;
}

export interface Imported {
  added: number;
  existing: number;
}

export interface LabelsBody {
  labels: string[];
}

export interface LogoDevBody {
  token?: string;
  secret?: string;
  clear?: boolean;
  clear_secret?: boolean;
}

export interface LogoDevFetch {
  started: boolean;
}

export interface LogoDevStatus {
  configured: boolean;
  searchable: boolean;
  with_logo: number;
  unknown: number;
  waiting: number;
  last_error: string | null;
}

export interface LoyaltyBody {
  person_id: number;
  kind: string;
  program: string;
  number?: string | null;
  expiry?: string | null;
  notes?: string | null;
}

export interface LoyaltyConflict {
  person_id: number;
  kind: string;
  program: string;
}

export interface LoyaltyEntry {
  id: number;
  person_id: number;
  kind: string;
  program: string;
  masked: string;
  readable: boolean;
  expiry: string | null;
  notes: string | null;
  logo: string | null;
}

export interface LoyaltyList {
  loyalty: LoyaltyEntry[];
  conflicts: LoyaltyConflict[];
  programs: Record<string, string[]>;
}

export interface Mailbox {
  id: number;
  address: string;
  status: "connected" | "reconnect" | "error";
  last_error: string | null;
  last_scan: string | null;
  scan_error: string | null;
  scanning: boolean;
  scan_notice: string | null;
  scan_summary: ScanSummary | null;
  reading_again: string | null;
  labels_picked: number;
  share_review: boolean;
}

export interface MailboxLabel {
  id: string;
  name: string;
  count: number;
  picked: boolean;
}

export interface MailboxLabels {
  labels: MailboxLabel[];
}

export interface MailboxList {
  configured: boolean;
  mailboxes: Mailbox[];
}

export interface MatchBody {
  entry: number;
  segment_id: number | null;
}

export interface Matched {
  ok: boolean;
  matched: number;
}

export interface McpConnection {
  id: number;
  client: string | null;
  who: string | null;
  scope: string[];
  created: string | null;
  last_used: string | null;
}

export interface McpMailBody {
  allow: boolean;
}

export interface McpSettings {
  allow_writes: boolean;
  oauth: boolean;
  url: string | null;
  reason: string | null;
  connections: McpConnection[];
}

export interface McpWritesBody {
  allow: boolean;
}

export interface MergeBody {
  merge: number;
  confirm?: boolean;
}

export interface MoveBody {
  trip_id: number | null;
  confirm?: boolean;
}

export interface Offline {
  trip: Trip | null;
  messages: OfflineMessages[];
}

export interface OfflineMessages {
  segment_id: number;
  emails: StoredEmail[];
}

export interface Ok {
  ok: boolean;
}

export interface People {
  people: Person[];
}

export interface Person {
  id: number;
  display_name: string;
  first_name: string | null;
  legal_name: string | null;
  aliases: string[];
  member: boolean;
  links: PersonLink[];
}

export interface PersonBody {
  display_name: string;
  first_name?: string | null;
  legal_name?: string | null;
  aliases?: string[];
}

export interface PersonLink {
  guest: string;
  by: string;
  on: string;
}

export interface Port {
  name: string;
  zone: string;
  arrive_local: string | null;
  depart_local: string | null;
}

export interface Preview {
  subject: string | null;
  text: string;
  html: string | null;
  truncated: boolean;
  original: boolean;
  images: number;
}

export interface Price {
  amount_minor: number;
  currency: string;
  source: "email" | "manual";
}

export interface PriceBody {
  amount_minor: number;
  currency: string;
}

export interface ReminderDevice {
  id: number;
  service: string;
  created: number;
}

export interface Reminders {
  public_key: string;
  check_in: boolean;
  day_of: boolean;
  devices: ReminderDevice[];
  feed: boolean;
}

export interface RemindersBody {
  check_in: boolean;
  day_of: boolean;
}

export interface Restored {
  ok: boolean;
  created: string | null;
  source: string | null;
  counts: Record<string, number>;
  safety_copy: string | null;
  unreadable_secrets: string[];
}

export interface Revealed {
  number: string;
}

export interface Review {
  items: ReviewItem[];
  matches: ReviewMatch[];
  who: WhoIsThis[];
  ai: boolean;
}

export interface ReviewBooking {
  kind: "flight" | "hotel" | "car" | "train" | "cruise" | "parking";
  provider: string | null;
  confirmation: string | null;
  origin: string | null;
  destination: string | null;
  start_local: string;
  end_local: string;
}

export interface ReviewCandidate {
  segment_id: number;
  trip_id: number;
  trip_name: string;
  kind: "flight" | "hotel" | "car" | "train" | "cruise" | "parking";
  provider: string | null;
  origin: string | null;
  destination: string | null;
  start_local: string;
  end_local: string;
}

export interface ReviewGlance {
  waiting: number;
  days: number;
  reasons: GlanceReason[];
  gaps: GlanceGap[];
  domains: GlanceDomain[];
  scans: GlanceScan[];
}

export interface ReviewItem {
  id: number;
  address: string;
  owner: string;
  mine: boolean;
  sender_domain: string;
  known_sender: boolean;
  holds_bookings: boolean;
  subject: string | null;
  has_email: boolean;
  received: string | null;
  reason: "no_markup" | "incomplete" | "broken" | "generic";
  suggestions: AiSuggestion[];
  suggestion_error: string | null;
  count: number;
  others: ReviewOther[];
}

export interface ReviewMatch {
  item_id: number;
  entry: number;
  subject: string | null;
  received: string | null;
  mine: boolean;
  booking: ReviewBooking;
  candidates: ReviewCandidate[];
}

export interface ReviewOther {
  id: number;
  subject: string | null;
  has_email: boolean;
  received: string | null;
}

export interface SameBooking {
  booking: ReviewCandidate | null;
}

export interface ScanStarted {
  started: boolean;
}

export interface ScanSummary {
  found: number;
  read: number;
  bookings: number;
  review: number;
  skipped: number;
  capped: boolean;
  labels_dropped: number;
  triaged: number;
  total: number;
  not_travel: number;
  followups: number;
  with_facts: number;
  attached: number;
}

export interface Segment {
  id: number;
  trip_id: number;
  kind: "flight" | "hotel" | "car" | "train" | "cruise" | "parking";
  status: "confirmed" | "changed" | "cancelled";
  confirmation: string | null;
  provider: string | null;
  start_local: string;
  start_zone: string;
  end_local: string;
  end_zone: string;
  origin: string | null;
  destination: string | null;
  details: Record<string, string>;
  manage_url: string | null;
  source: "manual" | "email" | "import";
  booked_by: number | null;
  locked_fields: string[];
  check_times: boolean;
  travelers: Traveler[];
  itinerary: Port[];
  days: CruiseDay[];
  logo: string | null;
  logo_label: string | null;
  hotel_brand: string | null;
  has_email: boolean;
  gate_code: GateCode | null;
  price: Price | null;
  links: SegmentLinks;
}

export interface SegmentBody {
  kind: "flight" | "hotel" | "car" | "train" | "cruise" | "parking";
  start_local: string;
  end_local: string;
  trip_id?: number | null;
  status?: "confirmed" | "changed" | "cancelled";
  confirmation?: string | null;
  provider?: string | null;
  start_zone?: string | null;
  end_zone?: string | null;
  origin?: string | null;
  destination?: string | null;
  details?: Record<string, string>;
  manage_url?: string | null;
  travelers?: TravelerBody[];
  itinerary?: Port[];
  price?: PriceBody | null;
}

export interface SegmentEdit {
  kind?: "flight" | "hotel" | "car" | "train" | "cruise" | "parking";
  status?: "confirmed" | "changed" | "cancelled";
  confirmation?: string | null;
  provider?: string | null;
  start_local?: string;
  start_zone?: string | null;
  end_local?: string;
  end_zone?: string | null;
  origin?: string | null;
  destination?: string | null;
  details?: Record<string, string>;
  manage_url?: string | null;
  travelers?: TravelerBody[];
  itinerary?: Port[];
  price?: PriceBody | null;
}

export interface SegmentEmails {
  emails: StoredEmail[];
}

export interface SegmentLinks {
  app: string | null;
  open: string | null;
  open_kind: "app" | "website" | null;
  directions: string | null;
  call: string | null;
}

export interface ShareBody {
  share: boolean;
}

export interface SignedIn {
  name: string | null;
  email: string | null;
  sub?: string;
  local?: boolean;
}

export interface SplitBody {
  segment_ids: number[];
}

export interface Started {
  url: string;
}

export interface State {
  version: string;
  database: "sqlite" | "postgres";
  user: SignedIn | null;
  last_backup: string | null;
  review_count: number;
  person_id: number | null;
  ai: boolean;
}

export interface Stats {
  years: number[];
  person: number | null;
  year: number | null;
  distance_unit: "mi" | "km";
  flights: StatsFlights;
  stays: StatsStays;
  cars: StatsCars;
  cruises: StatsCruises;
  parking: StatsParking;
  places: StatsPlaces;
}

export interface StatsAirline {
  code: string | null;
  name: string;
  flights: number;
}

export interface StatsAirport {
  code: string;
  name: string;
  city: string | null;
  country: string | null;
  visits: number;
  latitude: number | null;
  longitude: number | null;
}

export interface StatsCars {
  days: number;
  companies: StatsNamed[];
}

export interface StatsCruises {
  count: number;
  nights: number;
  sea_days: number;
  ports: number;
  lines: StatsNamed[];
}

export interface StatsFlightRecord {
  origin: string;
  destination: string;
  distance_km: number;
  start_local: string;
  flight_number: string | null;
}

export interface StatsFlights {
  count: number;
  distance_km: number;
  air_seconds: number;
  airports: StatsAirport[];
  airlines: StatsAirline[];
  countries: StatsNamed[];
  routes: StatsRoute[];
  cabins: StatsNamed[];
  top_seat: string | null;
  seat_positions: StatsSeats;
  longest: StatsFlightRecord | null;
  shortest: StatsFlightRecord | null;
  most_visited_airport: string | null;
  busiest_month: string | null;
  times_around_earth: number;
  moon_fraction: number;
}

export interface StatsMapTrip {
  trip_id: number;
  name: string;
  start: string;
  end: string;
}

export interface StatsNamed {
  name: string;
  count: number;
}

export interface StatsParking {
  days: number;
  bookings: number;
  lots: StatsNamed[];
}

export interface StatsPlace {
  name: string;
  first_visit: string;
  visits: number;
}

export interface StatsPlaces {
  countries: StatsPlace[];
  cities: StatsPlace[];
}

export interface StatsRoute {
  a: string;
  b: string;
  flights: number;
  distance_km: number | null;
  a_latitude: number | null;
  a_longitude: number | null;
  b_latitude: number | null;
  b_longitude: number | null;
  trips: StatsMapTrip[];
}

export interface StatsSeats {
  window: number;
  aisle: number;
  middle: number;
  unknown: number;
}

export interface StatsStayPin {
  city: string;
  country: string | null;
  latitude: number;
  longitude: number;
  stays: number;
  nights: number;
  trips: StatsMapTrip[];
}

export interface StatsStayPlace {
  name: string;
  stays: number;
  nights: number;
}

export interface StatsStayRecord {
  hotel: string | null;
  city: string | null;
  nights: number;
  start_local: string;
}

export interface StatsStays {
  nights: number;
  chains: StatsNamed[];
  cities: StatsNamed[];
  countries: StatsNamed[];
  count: number;
  average_nights: number;
  hotels: StatsStayPlace[];
  cities_by_nights: StatsStayPlace[];
  longest: StatsStayRecord | null;
  most_visited_hotel: StatsStayPlace | null;
  most_visited_city: StatsStayPlace | null;
  busiest_month: string | null;
  pins: StatsStayPin[];
}

export interface StoredEmail {
  subject: string | null;
  sender_domain: string | null;
  received: string | null;
  text: string;
  html: string | null;
  truncated: boolean;
  original: boolean;
  images: number;
}

export interface Traveler {
  id: number;
  person_id: number | null;
  name: string;
  seat: string | null;
}

export interface TravelerBody {
  person_id?: number | null;
  name?: string | null;
  seat?: string | null;
}

export interface Trip {
  id: number;
  name: string;
  start_date: string | null;
  end_date: string | null;
  destination: string | null;
  destination_manual: boolean;
  notes: string | null;
  auto: boolean;
  booked_by: number | null;
  emails: number;
  can_clear_emails: boolean;
  done_at: number | null;
  people: number[];
  costs: TripCosts;
  segments: Segment[];
}

export interface TripAirportPoint {
  code: string;
  city: string;
  latitude: number;
  longitude: number;
}

export interface TripBody {
  name?: string;
  destination?: string | null;
  notes?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  people?: number[];
  confirm?: boolean;
}

export interface TripCityPoint {
  city: string;
  latitude: number;
  longitude: number;
}

export interface TripCosts {
  totals: CostTotal[];
  priced: number;
  bookings: number;
}

export interface TripList {
  trips: Trip[];
}

export interface TripPlaces {
  airports: TripAirportPoint[];
  cities: TripCityPoint[];
  stays: TripStayPoint[];
  roads: TripRoads;
  boundaries: TripStateLine[];
}

export interface TripRoadLeg {
  from_segment_id: number;
  to_segment_id: number;
  refs: string[];
  points: number[][];
}

export interface TripRoadLine {
  ref: string;
  points: number[][];
}

export interface TripRoads {
  legs: TripRoadLeg[];
  interstates: TripRoadLine[];
}

export interface TripStateLine {
  points: number[][];
}

export interface TripStayPoint {
  segment_id: number;
  latitude: number;
  longitude: number;
  precision: "airport" | "zip" | "city";
}

export interface UnignoreBody {
  domain: string;
}

export interface WhoBody {
  person_id?: number;
  new_guest?: string;
}

export interface WhoIsThis {
  id: number;
  name: string;
  segment_id: number;
  trip_id: number;
  kind: "flight" | "hotel" | "car" | "train" | "cruise" | "parking";
  provider: string | null;
  origin: string | null;
  destination: string | null;
  start_local: string;
  start_zone: string;
}

export interface Endpoints {
  "GET /api/ai": { body: never; reply: AiSettings };
  "POST /api/ai": { body: AiBody; reply: AiSettings };
  "POST /api/backup/inspect": { body: never; reply: BackupContents };
  "POST /api/restore": { body: never; reply: Restored };
  "GET /api/people": { body: never; reply: People };
  "POST /api/people": { body: PersonBody; reply: Person };
  "POST /api/people/{id}": { body: PersonBody; reply: Person };
  "DELETE /api/people/{id}": { body: never; reply: Ok };
  "POST /api/people/{id}/claim": { body: never; reply: Person };
  "GET /api/people/claim-suggestions": { body: never; reply: ClaimSuggestions };
  "POST /api/people/claim-suggestions/dismiss": { body: never; reply: Ok };
  "GET /api/trips": { body: never; reply: TripList };
  "POST /api/trips": { body: TripBody; reply: Trip };
  "GET /api/trips/{id}": { body: never; reply: Trip };
  "POST /api/trips/{id}": { body: TripBody; reply: Trip };
  "DELETE /api/trips/{id}": { body: never; reply: Ok };
  "GET /api/trips/{id}/places": { body: never; reply: TripPlaces };
  "POST /api/trips/{id}/emails/clear": { body: never; reply: EmailsCleared };
  "POST /api/trips/{id}/merge": { body: MergeBody; reply: Trip };
  "POST /api/trips/{id}/split": { body: SplitBody; reply: Trip };
  "POST /api/trips/{id}/destination/suggest": { body: never; reply: DestinationSuggestion };
  "POST /api/segments": { body: SegmentBody; reply: Segment };
  "GET /api/segments/{id}": { body: never; reply: Segment };
  "POST /api/segments/{id}": { body: SegmentEdit; reply: Segment };
  "DELETE /api/segments/{id}": { body: never; reply: Ok };
  "GET /api/segments/{id}/emails": { body: never; reply: SegmentEmails };
  "POST /api/segments/{id}/code": { body: GateCodeBody; reply: Segment };
  "POST /api/segments/{id}/move": { body: MoveBody; reply: Trip };
  "GET /api/airports/{id}": { body: never; reply: Airport };
  "POST /api/import/preview": { body: never; reply: ImportPreview };
  "POST /api/import": { body: ImportBody; reply: Imported };
  "GET /api/stats": { body: never; reply: Stats };
  "GET /api/distance-unit": { body: never; reply: DistanceUnit };
  "POST /api/distance-unit": { body: DistanceUnitBody; reply: DistanceUnit };
  "GET /api/flight-status": { body: never; reply: FlightStatusList };
  "POST /api/flight-status/{id}": { body: never; reply: FlightStatusList };
  "GET /api/logodev": { body: never; reply: LogoDevStatus };
  "POST /api/logodev": { body: LogoDevBody; reply: LogoDevStatus };
  "POST /api/logodev/fetch": { body: never; reply: LogoDevFetch };
  "GET /api/loyalty": { body: never; reply: LoyaltyList };
  "POST /api/loyalty": { body: LoyaltyBody; reply: LoyaltyEntry };
  "POST /api/loyalty/{id}": { body: LoyaltyBody; reply: LoyaltyEntry };
  "DELETE /api/loyalty/{id}": { body: never; reply: Ok };
  "POST /api/loyalty/{id}/reveal": { body: never; reply: Revealed };
  "GET /api/mailboxes": { body: never; reply: MailboxList };
  "POST /api/mailboxes/connect": { body: never; reply: Started };
  "DELETE /api/mailboxes/{id}": { body: never; reply: Disconnected };
  "POST /api/mailboxes/{id}/scan": { body: never; reply: ScanStarted };
  "POST /api/mailboxes/{id}/share": { body: ShareBody; reply: Ok };
  "GET /api/mailboxes/{id}/labels": { body: never; reply: MailboxLabels };
  "POST /api/mailboxes/{id}/labels": { body: LabelsBody; reply: Ok };
  "POST /api/mailboxes/{id}/reread": { body: never; reply: ScanStarted };
  "POST /api/mailboxes/{id}/backfill": { body: never; reply: ScanStarted };
  "GET /api/mailboxes/{id}/ignored": { body: never; reply: IgnoredSenders };
  "GET /api/mailboxes/{id}/review-glance": { body: never; reply: ReviewGlance };
  "POST /api/mailboxes/{id}/unignore": { body: UnignoreBody; reply: ScanStarted };
  "GET /api/reminders": { body: never; reply: Reminders };
  "POST /api/reminders": { body: RemindersBody; reply: Reminders };
  "POST /api/reminders/devices": { body: DeviceBody; reply: ReminderDevice };
  "DELETE /api/reminders/devices/{id}": { body: never; reply: Ok };
  "POST /api/feed": { body: never; reply: FeedMade };
  "DELETE /api/feed": { body: never; reply: Ok };
  "GET /api/review": { body: never; reply: Review };
  "POST /api/review/who/{id}": { body: WhoBody; reply: Matched };
  "POST /api/review/{id}/ignore": { body: never; reply: Ignoring };
  "POST /api/review/{id}/match": { body: MatchBody; reply: Ok };
  "POST /api/review/{id}/same": { body: SegmentBody; reply: SameBooking };
  "POST /api/review/{id}/attach": { body: SegmentBody; reply: Attached };
  "GET /api/review/{id}/preview": { body: never; reply: Preview };
  "POST /api/review/{id}/suggest": { body: never; reply: Ok };
  "DELETE /api/review/{id}": { body: never; reply: Ok };
  "GET /api/mcp-settings": { body: never; reply: McpSettings };
  "POST /api/mcp-settings/writes": { body: McpWritesBody; reply: McpWritesBody };
  "POST /api/mcp-settings/connections/{id}/mail": { body: McpMailBody; reply: McpMailBody };
  "DELETE /api/mcp-settings/connections/{id}": { body: never; reply: Ok };
  "GET /api/assistant/review": { body: never; reply: AssistantItems };
  "GET /api/assistant/review/{id}": { body: never; reply: AssistantItemDetail };
  "GET /api/assistant/review/{id}/email": { body: never; reply: AssistantEmail };
  "POST /api/assistant/review/{id}/match": { body: AssistantMatchBody; reply: AssistantMatched };
  "POST /api/assistant/review/{id}/create": { body: AssistantCreateBody; reply: Segment };
  "POST /api/assistant/review/{id}/dismiss": { body: AssistantDismissBody; reply: AssistantDismissed };
  "GET /api/assistant/segments/{id}/email": { body: never; reply: AssistantSegmentEmails };
  "GET /api/state": { body: never; reply: State };
  "GET /api/offline": { body: never; reply: Offline };
}
