"""
Custom spaCy NLP pipeline for resume entity extraction.
Uses EntityRuler + PhraseMatcher for resume-specific NER.
Expanded skill matching with variations and word-boundary awareness.
"""

import logging
import spacy
from spacy.language import Language

logger = logging.getLogger('resume_engine.nlp')

# ─── Skill Patterns (expanded with variations) ──────────────────────────────

SKILL_PATTERNS = [
    # Programming Languages + variations
    "Python", "Python3", "Python Programming",
    "Java", "Java Programming", "Core Java", "Advanced Java",
    "JavaScript", "JS", "ES6", "ECMAScript",
    "TypeScript", "TS",
    "C++", "CPP", "C Plus Plus",
    "C#", "CSharp", "C Sharp",
    "C", "C Programming",
    "Go", "Golang",
    "Rust", "Ruby", "PHP",
    "Swift", "Kotlin", "Scala",
    "R", "R Programming",
    "Perl", "Dart", "Lua", "Haskell", "Elixir", "Clojure",
    "MATLAB", "Objective-C", "Assembly",
    # Web Frameworks
    "React", "React.js", "ReactJS",
    "Angular", "AngularJS", "Angular.js",
    "Vue", "Vue.js", "VueJS",
    "Next.js", "NextJS", "Nuxt.js", "NuxtJS",
    "Node.js", "NodeJS", "Node",
    "Express", "Express.js", "ExpressJS",
    "Django", "Flask", "FastAPI",
    "Spring", "Spring Boot", "SpringBoot",
    "Rails", "Ruby on Rails",
    "Laravel", "ASP.NET", ".NET", "Svelte", "SvelteKit",
    "Remix", "Gatsby", "Astro",
    # Databases
    "SQL", "NoSQL",
    "MongoDB", "Mongo",
    "PostgreSQL", "Postgres",
    "MySQL", "SQLite",
    "Redis", "Cassandra", "DynamoDB",
    "Firebase", "Firestore",
    "Elasticsearch", "Oracle", "MariaDB",
    "Neo4j", "CouchDB", "InfluxDB",
    # Cloud & DevOps
    "AWS", "Amazon Web Services",
    "Azure", "Microsoft Azure",
    "GCP", "Google Cloud", "Google Cloud Platform",
    "Docker", "Kubernetes", "K8s",
    "Terraform", "Ansible", "Puppet", "Chef",
    "Jenkins", "CI/CD", "CICD",
    "GitHub Actions", "GitLab CI", "CircleCI", "Travis CI",
    "Heroku", "Vercel", "Netlify", "DigitalOcean",
    "Nginx", "Apache", "Load Balancing",
    # Data Science / ML / AI
    "Machine Learning", "ML",
    "Deep Learning", "DL",
    "Artificial Intelligence", "AI",
    "NLP", "Natural Language Processing",
    "Computer Vision", "CV",
    "TensorFlow", "PyTorch", "Scikit-learn", "Sklearn",
    "Keras", "XGBoost", "LightGBM", "CatBoost",
    "Pandas", "NumPy", "Matplotlib", "Seaborn", "Plotly",
    "Data Science", "Data Analysis", "Data Analytics",
    "Data Engineering", "Data Mining", "Data Visualization",
    "Power BI", "Tableau", "Looker",
    "Apache Spark", "Spark", "Hadoop", "Hive", "Kafka",
    "ETL", "Data Pipeline", "Data Warehouse",
    "OpenCV", "YOLO", "Hugging Face", "LangChain",
    "GPT", "LLM", "Transformers", "BERT", "RAG",
    # Tools & Version Control
    "Git", "GitHub", "GitLab", "Bitbucket", "SVN",
    "Linux", "Unix", "Ubuntu", "CentOS",
    "Bash", "Shell Scripting", "PowerShell",
    "Vim", "VS Code", "Visual Studio",
    # Testing
    "Selenium", "Pytest", "JUnit", "Jest", "Cypress",
    "Mocha", "Chai", "TestNG", "Robot Framework",
    "Unit Testing", "Integration Testing", "TDD", "BDD",
    # APIs
    "Postman", "Swagger", "OpenAPI",
    "GraphQL", "REST", "REST API", "RESTful",
    "gRPC", "WebSocket", "WebSockets",
    "SOAP", "API Development",
    # Design & UI
    "Figma", "Sketch", "Adobe XD",
    "Adobe Photoshop", "Adobe Illustrator",
    "UI/UX", "UI Design", "UX Design",
    # Concepts & Methodologies
    "Microservices", "Monolithic",
    "Agile", "Scrum", "Kanban", "Waterfall",
    "OOP", "Object Oriented Programming",
    "Design Patterns", "System Design",
    "Data Structures", "Algorithms", "DSA",
    "Blockchain", "Solidity", "Web3", "Smart Contracts",
    "DevOps", "SRE", "MLOps", "AIOps",
    "SDLC", "Software Engineering",
    # Frontend
    "HTML", "HTML5",
    "CSS", "CSS3", "SASS", "SCSS", "LESS",
    "Tailwind", "TailwindCSS", "Tailwind CSS",
    "Bootstrap", "Material UI", "MUI",
    "Chakra UI", "Ant Design", "Styled Components",
    # Mobile
    "React Native", "Flutter", "Ionic",
    "Android", "Android Development",
    "iOS", "iOS Development",
    "Kotlin", "SwiftUI",
    # Security
    "Cybersecurity", "Penetration Testing", "OWASP",
    "Encryption", "SSL", "TLS", "OAuth", "JWT",
    # Other
    "RabbitMQ", "MQTT", "Celery",
    "WebRTC", "Socket.io",
    "Webpack", "Vite", "Babel", "ESLint",
    "NPM", "Yarn", "PNPM", "Pip",
    "Jira", "Confluence", "Trello", "Slack",
    "Arduino", "Raspberry Pi", "IoT",
    "OpenAI", "Gemini", "Claude",
]

# ─── Degree Patterns (comprehensive variations) ─────────────────────────────

DEGREE_PATTERNS = [
    # B.Tech variations
    "B.Tech", "BTech", "B. Tech", "B.Tech.",
    "B.E", "B.E.", "BE",
    "Bachelor of Technology", "Bachelor of Engineering",
    # B.Sc / B.A. / BCA / BBA
    "B.Sc", "B.Sc.", "BSc", "B.S.", "BS",
    "Bachelor of Science",
    "B.A.", "BA", "Bachelor of Arts",
    "BCA", "Bachelor of Computer Applications",
    "BBA", "Bachelor of Business Administration",
    "B.Com", "B.Com.", "BCom", "Bachelor of Commerce",
    # M.Tech variations
    "M.Tech", "MTech", "M. Tech", "M.Tech.",
    "M.E", "M.E.", "ME",
    "Master of Technology", "Master of Engineering",
    # M.Sc / M.A. / MCA / MBA
    "M.Sc", "M.Sc.", "MSc", "M.S.", "MS",
    "Master of Science",
    "M.A.", "MA", "Master of Arts",
    "MCA", "Master of Computer Applications",
    "MBA", "Master of Business Administration",
    "M.Com", "M.Com.", "MCom", "Master of Commerce",
    # PhD
    "Ph.D", "Ph.D.", "PhD", "Doctorate", "Doctor of Philosophy",
    # Generic
    "Bachelor's", "Master's", "Diploma",
    "Associate Degree", "Postgraduate",
    "Integrated", "Dual Degree",
    # Professional
    "MBBS", "MD", "LLB", "LLM",
    "B.Pharm", "M.Pharm",
    "B.Des", "M.Des",
    "B.Arch", "M.Arch",
    # International
    "Bachelor", "Master", "Graduate", "Undergraduate",
]


def create_nlp_pipeline():
    """
    Load spaCy model and add custom resume-specific entity patterns.
    Returns the configured nlp pipeline.
    """
    logger.info("🧠 Loading spaCy model: en_core_web_sm")
    nlp = spacy.load("en_core_web_sm")

    # ── Add EntityRuler BEFORE the default NER ──────────────────────────
    ruler = nlp.add_pipe("entity_ruler", before="ner", config={"overwrite_ents": True})

    patterns = []

    # Skill patterns — case-insensitive matching via lower
    for skill in SKILL_PATTERNS:
        patterns.append({"label": "SKILL", "pattern": skill})
        # Also add lowercase version for case-insensitive matching
        if skill != skill.lower():
            patterns.append({"label": "SKILL", "pattern": skill.lower()})

    # Degree patterns
    for degree in DEGREE_PATTERNS:
        patterns.append({"label": "DEGREE", "pattern": degree})
        if degree != degree.lower():
            patterns.append({"label": "DEGREE", "pattern": degree.lower()})

    # GitHub URL pattern (regex-based)
    patterns.append({
        "label": "GITHUB",
        "pattern": [{"TEXT": {"REGEX": r"github\.com/[A-Za-z0-9\-]+"}}]
    })

    # Phone patterns (regex-based)
    patterns.append({
        "label": "PHONE",
        "pattern": [{"TEXT": {"REGEX": r"[\+]?\d[\d\-\s]{8,15}\d"}}]
    })

    # Email pattern (regex-based)
    patterns.append({
        "label": "EMAIL",
        "pattern": [{"TEXT": {"REGEX": r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"}}]
    })

    ruler.add_patterns(patterns)
    logger.info(f"   ✅ EntityRuler loaded: {len(patterns)} patterns ({len(SKILL_PATTERNS)} skills, {len(DEGREE_PATTERNS)} degrees)")

    return nlp


# ─── Singleton: load once per process ────────────────────────────────────────

_nlp_instance = None


def get_nlp():
    """Get the shared NLP pipeline instance (lazy-loaded singleton)."""
    global _nlp_instance
    if _nlp_instance is None:
        _nlp_instance = create_nlp_pipeline()
    return _nlp_instance
