/**
 * The team, as one list every surface draws from.
 *
 * Membership is the author list: everyone marked "include as author" on the
 * contribution table, and nobody else. Two people who took part in the week but
 * are not on it are deliberately absent here — this list is credit, not
 * attendance.
 *
 * Names are stored split rather than as one string because the About page sorts
 * them, and the surname is not reliably the last word of a name — "Liedewei Van
 * de Vondel" is the one here that a computer would guess wrong, and the next
 * person added could be worse. Splitting it makes the sort key a fact somebody
 * wrote down instead of something the code inferred.
 *
 * Bios, links and photos come from issue #90, where people were asked to supply
 * their own. They are optional and most entries have none: the ask was opt-in,
 * so an entry with nothing but a name is the expected case, not a gap to fill in
 * on somebody's behalf. Text is quoted as it was given.
 */

export interface MemberLink {
  /** Where it points, in the reader's words — "Website", "ORCID", "Email". */
  label: string;
  href: string;
}

export interface Member {
  given: string;
  family: string;
  /** Only where the person publishes them; not inferred from a name. */
  pronouns?: string;
  /** Square headshot under public/team, supplied or pointed to by the person. */
  image?: string;
  /** One paragraph, in their own words. */
  bio?: string;
  links?: MemberLink[];
}

/** Source order is the contribution table's, so the two can be diffed by eye. */
const ROSTER: Member[] = [
  {
    given: "Harriet",
    family: "Dashnow",
    pronouns: "she/her",
    image: "/team/dashnow.jpg",
    bio: "Harriet Dashnow is an Assistant Professor in the Department of Biomedical Informatics at the University of Colorado Anschutz Medical Campus, where she leads a research group focused on developing computational methods to improve the diagnosis and understanding of rare genetic diseases, particularly those involving complex genetic variants like short tandem repeat (STR) expansions.",
    links: [
      { label: "Website", href: "https://harrietdashnow.com/" },
      { label: "Dashnow Lab", href: "https://dashnowlab.org/" },
      {
        label: "Google Scholar",
        href: "https://scholar.google.com/citations?user=4Y3m53gAAAAJ&hl=en",
      },
      { label: "ORCID", href: "https://orcid.org/0000-0001-8433-6270" },
      { label: "Bluesky", href: "https://bsky.app/profile/hdashnow.bsky.social" },
    ],
  },
  {
    given: "Akshay Kumar",
    family: "Avvaru",
    image: "/team/avvaru.jpg",
    bio: "Akshay Avvaru, PhD, is a postdoctoral fellow in the Dashnow Lab. Originally from Hyderabad, India, he earned his bachelor's degree in biotechnology before becoming a research trainee in the Bioinformatics Department at the Centre for Cellular and Molecular Biology (CCMB) in Hyderabad. Following his training, he completed his PhD in bioinformatics at CCMB. As a postdoctoral fellow, Avvaru will study the dynamics of STR polymorphism by utilizing population-scale genome datasets, with a particular focus on loci linked to genetic diseases.",
    links: [
      {
        label: "Google Scholar",
        href: "https://scholar.google.com/citations?user=jVBnGCwAAAAJ&hl=en",
      },
    ],
  },
  { given: "Bharati", family: "Jadhav" },
  { given: "Amit R", family: "Indap" },
  { given: "Garth", family: "Kong" },
  { given: "Sriram", family: "Sudarsanam" },
  { given: "Andrew", family: "Scouten" },
  { given: "Jordi", family: "Valls" },
  { given: "Ammara", family: "Saleem" },
  {
    given: "Elbay",
    family: "Aliyev",
    image: "/team/aliyev.jpg",
    bio: "Elbay Aliyev is a Senior Data Scientist and bioinformatician at the University of Colorado Anschutz Medical Campus. His work focuses on human genomics, particularly structural variants, copy-number variants, and tandem repeats. He develops computational pipelines for analyzing large-scale short- and long-read sequencing datasets and has contributed to population-genomics and rare-disease studies across multiple cohorts.",
    links: [
      { label: "Website", href: "https://dashnowlab.org/members/elbay-aliyev.html" },
      { label: "LinkedIn", href: "https://www.linkedin.com/in/elbayaliyev" },
      { label: "Email", href: "mailto:elbay.aliyev@cuanschutz.edu" },
    ],
  },
  {
    given: "Garrison",
    family: "Arner",
    image: "/team/arner.jpg",
    bio: "Gary Arner is an undergraduate student at Metropolitan State University of Denver where he is pursuing a Bachelor of Science in Data Science and Machine Learning with minors in math and computer science. He rotated in the Dashnow lab Nov 2025 - Jan 2026 as part of the PATH-GREU program then joined the lab for a one-year research project May 2026.",
  },
  { given: "Gavin", family: "Monahan" },
  { given: "Anukrati", family: "Sharma" },
  {
    given: "Liedewei",
    family: "Van de Vondel",
    bio: "Liedewei Van de Vondel is a Postdoctoral Researcher at the University of Miami, in the lab of Prof. Dr. Stephan Züchner. Her work focuses on identifying novel genetic causes of rare neurological and neuromuscular diseases, using state-of-the-art technologies like long-read sequencing to bring cutting-edge analysis methods into translational research.",
    links: [
      {
        label: "LinkedIn",
        href: "https://www.linkedin.com/in/liedewei-van-de-vondel-3b78a5133/",
      },
      { label: "Email", href: "mailto:lxv522@miami.edu" },
    ],
  },
  { given: "Divya", family: "Kalra" },
  { given: "Chantera", family: "Lazard" },
  { given: "Taimoor", family: "Khan" },
  { given: "Medhat", family: "Mahmoud" },
  {
    given: "MD Shakhaowat",
    family: "Hossain",
    image: "/team/hossain.jpg",
    bio: "MD Shakhaowat Hossain is a PhD candidate in Biomedical Sciences at the Center for Biomedical Informatics and Genomics, Tulane University School of Medicine, working with Dr. Loren Gragert on HLA immunogenetics, transplant informatics and health equity. His research applies population genetics and statistical modelling to donor-recipient HLA matching in organ allocation, from matchability metrics that give candidates with rare HLA genotypes fairer access to deceased-donor kidneys, to imputation methods that resolve ambiguous donor typing in the national match run. At this hackathon he worked on the cohort-level analysis of the inTRuder call set, covering non-reference insertion burden across ancestry groups, trio-based error estimation, and an hg38 tandem-repeat catalogue builder.",
    links: [
      { label: "Website", href: "https://www.shakhaowat.com/" },
      { label: "LinkedIn", href: "https://www.linkedin.com/in/md-shakhaowat-hossain/" },
      { label: "GitHub", href: "https://github.com/hossainms" },
      { label: "Email", href: "mailto:mhossain1@tulane.edu" },
    ],
  },
];

/**
 * Alphabetical by surname — the order an author list is read in, and the only
 * ordering on a list this long that lets somebody find themselves.
 * localeCompare rather than `<` so accented surnames sort where a reader
 * expects them rather than after Z.
 */
export const TEAM: Member[] = [...ROSTER].sort(
  (a, b) => a.family.localeCompare(b.family) || a.given.localeCompare(b.given),
);

export function fullName({ given, family }: Member): string {
  return `${given} ${family}`;
}

/**
 * Initials for the placeholder portrait. First letter of each stored half, so
 * "Van de Vondel" contributes its V rather than the d that a word-splitting
 * heuristic would find.
 */
export function initials({ given, family }: Member): string {
  return `${given[0]}${family[0]}`.toUpperCase();
}
