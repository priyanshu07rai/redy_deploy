"""
GitHub API integration for profile verification.
Uses the GitHub REST API v3 with PAT authentication.
Scoring formula:
  Account Age        (15%)
  Public Repos       (10%)
  Commit Activity    (20%)
  Language Diversity (10%)
  Stars Earned       (10%)
  Original Repos     (15%)
  Recent Activity    (10%)
  Profile Complete   (10%)
"""

import math
from datetime import datetime, timezone
import requests
from flask import current_app
import logging

logger = logging.getLogger('resume_engine')


def fetch_github_profile(username: str) -> dict:
    """
    Fetch GitHub profile data and compute Authenticity Score.
    """
    if not username or not username.strip():
        return {'github_score': 0, 'error': 'No username provided'}

    username = username.strip()

    token = current_app.config.get('GITHUB_TOKEN')
    headers = {'Accept': 'application/vnd.github.v3+json'}
    if token:
        headers['Authorization'] = f'token {token}'

    try:
        # 1. Fetch Basic Profile
        user_resp = requests.get(
            f'https://api.github.com/users/{username}',
            headers=headers, timeout=10
        )

        if user_resp.status_code == 404:
            return {'github_score': 0, 'error': f'User "{username}" not found'}
        if user_resp.status_code == 403:
            return {'github_score': 0, 'error': 'GitHub API rate limit exceeded'}
        if user_resp.status_code != 200:
            return {'github_score': 0, 'error': f'GitHub API returned {user_resp.status_code}'}

        user_data = user_resp.json()
        public_repos = user_data.get('public_repos', 0)
        followers = user_data.get('followers', 0)
        created_at = user_data.get('created_at', '')

        # Account age
        try:
            created_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            age_years = (datetime.now(timezone.utc) - created_date).days / 365.25
        except Exception:
            age_years = 0
            created_date = datetime.now(timezone.utc)

        # 2. Fetch Repos
        repos_resp = requests.get(
            f'https://api.github.com/users/{username}/repos',
            params={'sort': 'updated', 'per_page': 100},
            headers=headers, timeout=10
        )
        repos_data = repos_resp.json() if repos_resp.status_code == 200 else []

        # Analyze repos
        languages = {}
        total_stars = 0
        latest_push_date = created_date
        total_forks = 0
        six_months_ago = datetime.now(timezone.utc).timestamp() - (180 * 24 * 60 * 60)
        recently_active_repos = 0
        empty_repos = 0

        for repo in repos_data:
            if repo.get('fork'):
                total_forks += 1
                continue  # ignore forks for language/star count

            lang = repo.get('language')
            if lang:
                languages[lang] = languages.get(lang, 0) + 1
            else:
                empty_repos += 1

            total_stars += repo.get('stargazers_count', 0)

            pushed_at = repo.get('pushed_at')
            if pushed_at:
                try:
                    pushed_date = datetime.fromisoformat(pushed_at.replace('Z', '+00:00'))
                    if pushed_date > latest_push_date:
                        latest_push_date = pushed_date
                    if pushed_date.timestamp() > six_months_ago:
                        recently_active_repos += 1
                except Exception:
                    pass

        original_repos_count = len(repos_data) - total_forks

        # Primary Languages as % breakdown
        lang_percentages = {}
        total_lang_repos = sum(languages.values())
        if total_lang_repos > 0:
            for lang_name, count in sorted(languages.items(), key=lambda x: x[1], reverse=True)[:5]:
                lang_percentages[lang_name] = round((count / total_lang_repos) * 100)

        # Days since last activity
        days_since_active = (datetime.now(timezone.utc) - latest_push_date).days
        if days_since_active < 0:
            days_since_active = 0

        last_activity_str = f"{days_since_active} days ago"
        if days_since_active == 0:
            last_activity_str = "Today"
        elif days_since_active == 1:
            last_activity_str = "Yesterday"
        elif days_since_active > 365:
            last_activity_str = f"{round(days_since_active / 365, 1)} years ago"
        elif days_since_active > 30:
            last_activity_str = f"{round(days_since_active / 30)} months ago"

        # ─── Authenticity Score Formula (100 pts total) ─────────────────────
        # Account Age: 15 pts (3 pts/year up to 5 years)
        score_age = min(age_years * 3.0, 15.0)

        # Public Repos Count: 10 pts (1 pt per repo up to 10)
        score_repos = min(float(public_repos), 10.0)

        # Commit Activity last 6 months: 20 pts (3.3 pts per recently-active repo up to 6)
        score_commits = min(recently_active_repos * 3.33, 20.0)

        # Language Diversity: 10 pts (2.5 pts per language up to 4)
        score_lang = min(len(languages) * 2.5, 10.0)

        # Stars Earned: 10 pts (2 pts per star up to 5 stars)
        score_stars = min(total_stars * 2.0, 10.0)

        # Original Repos: 15 pts (1.5 pts per original repo up to 10)
        score_original = min(original_repos_count * 1.5, 15.0)

        # Recent Activity: 10 pts (full if active within 30 days, decays)
        if days_since_active <= 30:
            score_recent = 10.0
        elif days_since_active <= 90:
            score_recent = 7.0
        elif days_since_active <= 180:
            score_recent = 4.0
        elif days_since_active <= 365:
            score_recent = 2.0
        else:
            score_recent = 0.0

        # Profile Completeness: 10 pts
        score_complete = 0.0
        if user_data.get('bio'):
            score_complete += 3.0
        if user_data.get('company') or user_data.get('location'):
            score_complete += 3.0
        if user_data.get('blog') or user_data.get('twitter_username'):
            score_complete += 2.0
        if followers > 5:
            score_complete += 2.0

        github_score = round(
            score_age + score_repos + score_commits + score_lang +
            score_stars + score_original + score_recent + score_complete
        )
        github_score = min(github_score, 100)

        # ─── Fraud / Risk Heuristics ─────────────────────────────────────────
        github_flags = []
        fork_ratio = round((total_forks / len(repos_data)) * 100) if repos_data else 0

        if len(repos_data) > 3 and fork_ratio > 90:
            github_flags.append("90%+ repos are forks — low original contribution signal")
            github_score = int(github_score * 0.5)

        if days_since_active > 365:
            github_flags.append("No push activity in 12+ months — possibly inactive")
            github_score = int(github_score * 0.75)

        if public_repos > 0 and original_repos_count == 0:
            github_flags.append("All repos are forks or empty — no personal projects found")

        if empty_repos > original_repos_count and original_repos_count > 0:
            github_flags.append("High ratio of empty repositories detected")

        github_flag_reason = "; ".join(github_flags) if github_flags else ""

        github_summary = (
            f"Account is {round(age_years, 1)} years old with {original_repos_count} original "
            f"repos across {len(languages)} languages. "
            f"{'Recently active.' if days_since_active < 90 else 'Low recent activity.'}"
        )

        # Badge assignment
        if github_score >= 80:
            badge = '🟢 Verified Developer'
        elif github_score >= 50:
            badge = '🟡 Moderate Signal'
        else:
            badge = '🔴 Low Activity / Risk'

        return {
            'username': username,
            'github_score': github_score,
            'github_flag_reason': github_flag_reason,
            'github_summary': github_summary,
            'badge': badge,
            'public_repos': public_repos,
            'followers': followers,
            'account_age_years': round(age_years, 1),
            'primary_languages': lang_percentages,
            'last_activity': last_activity_str,
            'profile_url': user_data.get('html_url', ''),
            'avatar_url': user_data.get('avatar_url', ''),
            'bio': user_data.get('bio', ''),
            'stars': total_stars,
            'fork_ratio': fork_ratio,
            'original_repos': original_repos_count,
            'error': None,
            # Per-component scores for UI breakdown
            'score_breakdown': {
                'Account Age': round(score_age, 1),
                'Repos Count': round(score_repos, 1),
                'Commit Activity': round(score_commits, 1),
                'Language Diversity': round(score_lang, 1),
                'Stars Earned': round(score_stars, 1),
                'Original Work': round(score_original, 1),
                'Recent Activity': round(score_recent, 1),
                'Profile Completeness': round(score_complete, 1),
            }
        }

    except requests.exceptions.Timeout:
        return {'github_score': 0, 'error': 'GitHub API timeout'}
    except requests.exceptions.ConnectionError:
        return {'github_score': 0, 'error': 'Network error connecting to GitHub'}
    except Exception as e:
        logger.error(f"GitHub Verification Error: {str(e)}")
        return {'github_score': 0, 'error': f"Processing error: {str(e)}"}
