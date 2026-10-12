const EASTERN = ["Eastern", "EST", "EDT", "ET"];
const CENTRAL = ["Central", "CST", "CDT", "CT"];
const MOUNTAIN = ["Mountain", "MST", "MDT", "MT"];
const PACIFIC = ["Pacific", "PST", "PDT", "PT"];

const ENTRIES: [string, string[]][] = [
  ["America/New_York", [...EASTERN, "New York", "NY", "New Jersey", "NJ", "Pennsylvania", "PA", "Massachusetts", "MA", "Connecticut", "CT", "Rhode Island", "RI", "Vermont", "VT", "New Hampshire", "NH", "Maine", "ME", "Maryland", "MD", "Delaware", "DE", "District of Columbia", "DC", "Washington DC", "Virginia", "VA", "West Virginia", "WV", "North Carolina", "NC", "South Carolina", "SC", "Georgia", "GA", "Ohio", "OH"]],
  ["America/Detroit", EASTERN],
  ["America/Toronto", [...EASTERN, "Ontario", "ON", "Quebec", "QC", "Montreal"]],
  ["America/Chicago", [...CENTRAL, "Illinois", "IL", "Minnesota", "MN", "Wisconsin", "WI", "Missouri", "MO", "Iowa", "IA", "Arkansas", "AR", "Louisiana", "LA", "Mississippi", "MS", "Alabama", "AL", "Oklahoma", "OK"]],
  ["America/Winnipeg", [...CENTRAL, "Manitoba", "MB"]],
  ["America/Regina", ["Saskatchewan", "SK"]],
  ["America/Mexico_City", [...CENTRAL, "Mexico"]],
  ["America/Denver", [...MOUNTAIN, "Colorado", "CO", "New Mexico", "NM", "Utah", "UT", "Montana", "MT", "Wyoming", "WY"]],
  ["America/Edmonton", [...MOUNTAIN, "Alberta", "AB"]],
  ["America/Phoenix", ["Arizona", "AZ", "MST"]],
  ["America/Los_Angeles", [...PACIFIC, "California", "CA", "Washington", "WA", "Nevada", "NV"]],
  ["America/Vancouver", [...PACIFIC, "British Columbia", "BC"]],
  ["America/Anchorage", ["Alaska", "AK", "AKST", "AKDT"]],
  ["Pacific/Honolulu", ["Hawaii", "HI", "HST"]],
  ["America/Halifax", ["Atlantic", "Nova Scotia", "NS", "AST", "ADT"]],
  ["America/St_Johns", ["Newfoundland", "NL"]],
  ["America/Sao_Paulo", ["Brazil"]],
  ["Europe/London", ["GMT", "UTC", "UK", "United Kingdom", "Britain", "Great Britain", "England", "Scotland", "Wales", "BST"]],
  ["Atlantic/Reykjavik", ["GMT", "UTC", "Iceland"]],
  ["Africa/Abidjan", ["GMT", "UTC"]],
  ["Europe/Dublin", ["Ireland"]],
  ["Europe/Paris", ["France", "CET", "CEST"]],
  ["Europe/Berlin", ["Germany", "CET", "CEST"]],
  ["Europe/Madrid", ["Spain"]],
  ["Europe/Rome", ["Italy"]],
  ["Europe/Amsterdam", ["Netherlands", "Holland"]],
  ["Europe/Zurich", ["Switzerland"]],
  ["Asia/Tokyo", ["Japan", "JST"]],
  ["Asia/Calcutta", ["India", "Kolkata", "IST"]],
  ["Asia/Shanghai", ["China", "Beijing"]],
  ["Asia/Seoul", ["Korea", "South Korea"]],
  ["Asia/Singapore", ["Singapore"]],
  ["Asia/Dubai", ["UAE", "United Arab Emirates"]],
  ["Australia/Sydney", ["Australia", "New South Wales", "AEST", "AEDT"]],
  ["Pacific/Auckland", ["New Zealand", "NZST", "NZDT"]],
];

export const COMMON_NAMES: Record<string, string[]> = Object.fromEntries(ENTRIES);
