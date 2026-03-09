"""Verification script for Phase 3 Interview Engine"""
import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))

print("=" * 60)
print("PHASE 3 — INTERVIEW ENGINE VERIFICATION")
print("=" * 60)

# Test 1: Database migration
print("\n[1] Database Migration...")
from database import init_db
init_db()
import sqlite3
conn = sqlite3.connect('database.sqlite')
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='interviews'").fetchone()
cols = conn.execute('PRAGMA table_info(interviews)').fetchall()
col_names = [c[1] for c in cols]
assert tables is not None, "interviews table not found!"
assert 'integrity_index' in col_names, "integrity_index column missing!"
assert 'baseline_answer_score' in col_names, "baseline_answer_score column missing!"
assert 'interview_hash' in col_names, "interview_hash column missing!"
print(f"  ✓ interviews table exists with {len(cols)} columns")
conn.close()

# Test 2: Integrity index computation
print("\n[2] Integrity Index Computation...")
from interview_engine.integrity_monitor import compute_integrity_index, get_anomaly_breakdown
score1 = compute_integrity_index({
    'tab_switches': 2, 'window_blur': 1, 'no_face_seconds': 10,
    'multiple_faces': 0, 'copy_attempts': 0, 'fullscreen_exits': 1
})
assert score1 == 73.0, f"Expected 73.0, got {score1}"
print(f"  ✓ Score with anomalies: {score1}")

score2 = compute_integrity_index({})
assert score2 == 100.0, f"Expected 100.0, got {score2}"
print(f"  ✓ Clean session score: {score2}")

score3 = compute_integrity_index({
    'tab_switches': 50, 'window_blur': 50, 'no_face_seconds': 500,
    'multiple_faces': 10, 'copy_attempts': 10, 'fullscreen_exits': 10
})
assert score3 == 0.0, f"Expected 0.0, got {score3}"
print(f"  ✓ Max penalty clamped to: {score3}")

breakdown = get_anomaly_breakdown({'tab_switches': 3, 'multiple_faces': 2})
assert len(breakdown) == 2, f"Expected 2 breakdown items, got {len(breakdown)}"
print(f"  ✓ Anomaly breakdown: {len(breakdown)} items")

# Test 3: Transcript processing
print("\n[3] Transcript Processing...")
from interview_engine.transcript_processor import process_transcript
metrics = process_transcript(
    "I have extensive experience with Python and Django development. "
    "I built several microservices using Flask and FastAPI. "
    "I managed a team of developers and improved our CI/CD pipeline. "
    "My approach focuses on clean code and testing. "
    "I have worked with Docker and Kubernetes for deployment. "
    "I also have experience with machine learning and data science projects."
)
assert metrics['word_count'] > 0, "word_count is 0!"
assert len(metrics['matched_keywords']) > 0, "No keywords matched!"
print(f"  ✓ Words: {metrics['word_count']}")
print(f"  ✓ Fillers: {metrics['filler_count']}")
print(f"  ✓ Keywords matched: {len(metrics['matched_keywords'])}")
print(f"  ✓ Vocabulary richness: {metrics['vocabulary_richness']}")

# Empty transcript test
empty = process_transcript("")
assert empty['word_count'] == 0, "Empty transcript should have 0 words"
print(f"  ✓ Empty transcript handled correctly")

# Test 4: Deterministic scoring
print("\n[4] Deterministic Answer Scoring...")
from interview_engine.deterministic_scorer import compute_baseline_score, compute_final_answer_score
baseline = compute_baseline_score(metrics)
assert 0 <= baseline <= 100, f"Baseline out of range: {baseline}"
print(f"  ✓ Baseline score: {baseline}")

final = compute_final_answer_score(baseline, 75.0)
expected = round(0.70 * baseline + 0.30 * 75.0, 2)
assert final == expected, f"Final mismatch: {final} vs {expected}"
print(f"  ✓ Final score (AI=75): {final}")

zero_baseline = compute_baseline_score({'word_count': 0})
assert zero_baseline == 0.0, f"Empty transcript baseline should be 0, got {zero_baseline}"
print(f"  ✓ Empty transcript baseline: {zero_baseline}")

# Test 5: Hashing
print("\n[5] Hash Generation & Verification...")
from interview_engine.hashing import generate_interview_hash, verify_hash
hash1 = generate_interview_hash("nonexistent.webm", "test transcript", 85.0, 72.5)
hash2 = generate_interview_hash("nonexistent.webm", "test transcript", 85.0, 72.5)
assert hash1 == hash2, "Same inputs should produce same hash!"
print(f"  ✓ Deterministic hashing: {hash1[:32]}...")

hash3 = generate_interview_hash("nonexistent.webm", "different transcript", 85.0, 72.5)
assert hash1 != hash3, "Different inputs should produce different hash!"
print(f"  ✓ Different inputs → different hash")

verified = verify_hash("nonexistent.webm", "test transcript", 85.0, 72.5, hash1)
assert verified == True, "Valid hash should verify!"
print(f"  ✓ Hash verification: PASS")

tampered = verify_hash("nonexistent.webm", "tampered transcript", 85.0, 72.5, hash1)
assert tampered == False, "Tampered hash should fail!"
print(f"  ✓ Tamper detection: CAUGHT")

# Test 6: App creation with all routes
print("\n[6] Full App Route Registration...")
from app import create_app
app = create_app()
rules = [str(r) for r in app.url_map.iter_rules()]
interview_routes = sorted([r for r in rules if 'interview' in r])
assert len(interview_routes) >= 4, f"Expected ≥4 interview routes, got {len(interview_routes)}"
for r in interview_routes:
    print(f"  ✓ {r}")

print("\n" + "=" * 60)
print("ALL TESTS PASSED ✓")
print("=" * 60)
