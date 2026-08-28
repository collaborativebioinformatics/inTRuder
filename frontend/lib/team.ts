/**
 * The team, as one list every surface draws from.
 *
 * Names are stored split rather than as one string because the About page sorts
 * them, and the surname is not reliably the last word of a name — "Liedewei Van
 * de Vondel" is the one here that a computer would guess wrong, and the next
 * person added could be worse. Splitting it makes the sort key a fact somebody
 * wrote down instead of something the code inferred.
 */

export interface Member {
  given: string;
  family: string;
}

/** Source order is the README's, so the two lists can be diffed by eye. */
const ROSTER: Member[] = [
  { given: "Harriet", family: "Dashnow" },
  { given: "Akshay Kumar", family: "Avvaru" },
  { given: "Bharati", family: "Jadhav" },
  { given: "Amit R", family: "Indap" },
  { given: "Garth", family: "Kong" },
  { given: "Achisha", family: "Saikia" },
  { given: "Sriram", family: "Sudarsanam" },
  { given: "Andrew", family: "Scouten" },
  { given: "Jordi", family: "Valls" },
  { given: "Ammara", family: "Saleem" },
  { given: "Elbay", family: "Aliyev" },
  { given: "Garrison", family: "Arner" },
  { given: "Gavin", family: "Monahan" },
  { given: "Anukrati", family: "Sharma" },
  { given: "Liedewei", family: "Van de Vondel" },
  { given: "Ramakrishnan", family: "Rajagopalan" },
  { given: "Divya", family: "Kalra" },
  { given: "Chantera", family: "Lazard" },
  { given: "Taimoor", family: "Khan" },
  { given: "Medhat", family: "Mahmoud" },
];

/**
 * Alphabetical by surname — the order an author list is read in, and the only
 * ordering on a twenty-name list that lets somebody find themselves.
 * localeCompare rather than `<` so accented surnames sort where a reader
 * expects them rather than after Z.
 */
export const TEAM: Member[] = [...ROSTER].sort(
  (a, b) => a.family.localeCompare(b.family) || a.given.localeCompare(b.given),
);

export function fullName({ given, family }: Member): string {
  return `${given} ${family}`;
}
