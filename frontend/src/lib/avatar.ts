export type AvatarPerson = { id?: number | null; name: string };

export const AVATAR_TONES = [
  "bg-avatar-1 text-avatar-1-ink",
  "bg-avatar-2 text-avatar-2-ink",
  "bg-avatar-3 text-avatar-3-ink",
  "bg-avatar-4 text-avatar-4-ink",
  "bg-avatar-5 text-avatar-5-ink",
  "bg-avatar-6 text-avatar-6-ink",
] as const;

export const avatarTone = (person: AvatarPerson): string => {
  if (person.id != null) return AVATAR_TONES[Math.abs(person.id) % AVATAR_TONES.length];
  let hash = 0;
  for (const ch of person.name) hash = (hash * 31 + ch.codePointAt(0)!) >>> 0;
  return AVATAR_TONES[hash % AVATAR_TONES.length];
};
