export type AvatarPerson = { id?: number | null; name: string };

export const AVATAR_TONES = [
  "bg-[#1d3a63] text-[#d6e6ff]",
  "bg-[#14463c] text-[#c9f3e6]",
  "bg-[#4a2f63] text-[#ecdcff]",
  "bg-[#5a3a12] text-[#ffe3b3]",
  "bg-[#5a2433] text-[#ffd6df]",
  "bg-[#2f3a4f] text-[#dbe3f2]",
] as const;

export const avatarTone = (person: AvatarPerson): string => {
  if (person.id != null) return AVATAR_TONES[Math.abs(person.id) % AVATAR_TONES.length];
  let hash = 0;
  for (const ch of person.name) hash = (hash * 31 + ch.codePointAt(0)!) >>> 0;
  return AVATAR_TONES[hash % AVATAR_TONES.length];
};
