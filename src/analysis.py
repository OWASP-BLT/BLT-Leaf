"""
PR analysis functions for review progress, health classification, and readiness scoring
"""
from datetime import datetime, timezone


# Score multiplier when changes are requested
# Reduces overall readiness score by 50% when reviewers request changes
_CHANGES_REQUESTED_SCORE_MULTIPLIER = 0.5

# Score multiplier when PR has merge conflicts
# Reduces overall readiness score by 33% when mergeable state is 'dirty' (conflicts)
_MERGE_CONFLICTS_SCORE_MULTIPLIER = 0.67


def analyze_review_progress(timeline, pr_author):
    """
    Analyze review feedback loops and author responsiveness
    
    Args:
        timeline: List of timeline events from build_pr_timeline()
        pr_author: GitHub login of PR author
    
    Returns:
        Dict with:
        {
            'feedback_loops': List of feedback/response pairs,
            'total_feedback_count': int,
            'responded_count': int,
            'response_rate': float (0-1),
            'awaiting_author': bool,
            'awaiting_reviewer': bool,
            'stale_feedback': List of unaddressed feedback,
            'latest_review_state': str or None,
            'last_reviewer_action': datetime or None,
            'last_author_action': datetime or None
        }
    """
    feedback_loops = []
    latest_review_state = None
    last_reviewer_action = None
    last_author_action = None
    
    # Iterate through timeline to detect feedback patterns
    for event in timeline:
        author = event['author']
        timestamp = event['timestamp']
        event_type = event['type']
        
        # Track reviewer actions (reviews and comments from non-authors)
        if event_type in ['review', 'review_comment'] and author != pr_author:
            last_reviewer_action = timestamp
            
            # Update latest review state
            if event_type == 'review':
                latest_review_state = event['data'].get('state', '')
            
            # Create feedback loop entry
            feedback_loops.append({
                'reviewer': author,
                'feedback_time': timestamp,
                'feedback_type': event_type,
                'author_responded': False,
                'response_time': None,
                'response_type': None,
                'response_delay_hours': None
            })
        
        # Track author actions (commits and comments from author)
        elif author == pr_author and event_type in ['commit', 'issue_comment', 'review_comment']:
            last_author_action = timestamp
            
            # Check if this responds to pending feedback
            # Match to the most recent unresponded feedback
            for loop in reversed(feedback_loops):
                if not loop['author_responded'] and loop['feedback_time'] < timestamp:
                    loop['author_responded'] = True
                    loop['response_time'] = timestamp
                    loop['response_type'] = event_type
                    
                    # Calculate delay in hours
                    delay = (timestamp - loop['feedback_time']).total_seconds() / 3600
                    loop['response_delay_hours'] = round(delay, 1)
                    break
    
    # Calculate response metrics
    total_feedback = len(feedback_loops)
    responded_count = sum(1 for loop in feedback_loops if loop['author_responded'])
    response_rate = responded_count / total_feedback if total_feedback > 0 else 1.0
    
    # Determine current state
    awaiting_author = (
        latest_review_state == 'CHANGES_REQUESTED' or
        (last_reviewer_action and 
         (not last_author_action or last_reviewer_action > last_author_action))
    )
    
    awaiting_reviewer = (
        not awaiting_author and
        last_author_action and
        (not last_reviewer_action or last_author_action > last_reviewer_action)
    )
    
    # Find stale feedback (older than 3 days without response)
    now = datetime.now(timezone.utc)
    stale_threshold_hours = 72  # 3 days
    
    stale_feedback = []
    for loop in feedback_loops:
        if not loop['author_responded']:
            hours_old = (now - loop['feedback_time']).total_seconds() / 3600
            if hours_old > stale_threshold_hours:
                stale_feedback.append({
                    'reviewer': loop['reviewer'],
                    'feedback_type': loop['feedback_type'],
                    'days_old': round(hours_old / 24, 1)
                })
    
    return {
        'feedback_loops': feedback_loops,
        'total_feedback_count': total_feedback,
        'responded_count': responded_count,
        'response_rate': response_rate,
        'awaiting_author': awaiting_author,
        'awaiting_reviewer': awaiting_reviewer,
        'stale_feedback': stale_feedback,
        'latest_review_state': latest_review_state,
        'last_reviewer_action': last_reviewer_action.isoformat() if last_reviewer_action else None,
        'last_author_action': last_author_action.isoformat() if last_author_action else None
    }


def classify_review_health(review_data):
    """
    Classify review health and assign score (0-100)
    
    Args:
        review_data: Output from analyze_review_progress()
    
    Returns:
        Tuple of (classification: str, score: int)
        
        Classifications:
        - APPROVED: 90-100 - Reviews approved
        - ACTIVE: 70-85 - Good progress, responsive
        - AWAITING_REVIEWER: 60-80 - Waiting on reviewers
        - AWAITING_AUTHOR: 35-55 - Needs author response
        - STALLED: 10-30 - No activity or unaddressed feedback
        - NO_ACTIVITY: 50 - No reviews or feedback yet
    """
    response_rate = review_data['response_rate']
    stale_count = len(review_data['stale_feedback'])
    awaiting_author = review_data['awaiting_author']
    awaiting_reviewer = review_data['awaiting_reviewer']
    latest_state = review_data['latest_review_state']
    total_feedback = review_data['total_feedback_count']
    
    # No feedback yet
    if total_feedback == 0:
        return ('NO_ACTIVITY', 50)
    
    # Approved state
    if latest_state == 'APPROVED':
        return ('APPROVED', 95)
    
    # Stalled (has stale feedback)
    if stale_count > 0:
        # More stale feedback = lower score
        score = max(10, 50 - (stale_count * 15))
        return ('STALLED', score)
    
    # Awaiting author with poor response rate
    if awaiting_author and response_rate < 0.5:
        return ('AWAITING_AUTHOR', 35)
    
    # Awaiting author with good response rate
    if awaiting_author:
        return ('AWAITING_AUTHOR', 55)
    
    # Awaiting reviewer
    if awaiting_reviewer:
        # Higher score if author has been responsive
        score = 70 + int(response_rate * 10)
        return ('AWAITING_REVIEWER', min(score, 80))
    
    # Active (good back and forth)
    if response_rate > 0.7:
        return ('ACTIVE', 85)
    
    # Default active state
    return ('ACTIVE', 70)


def calculate_ci_confidence(checks_passed, checks_failed, checks_skipped):
    """
    Calculate CI confidence score from check results
    
    Args:
        checks_passed: Number of passing checks
        checks_failed: Number of failing checks
        checks_skipped: Number of skipped checks
    
    Returns:
        int: Confidence score 0-100
    """
    total_checks = checks_passed + checks_failed + checks_skipped
    
    # No checks = neutral score
    if total_checks == 0:
        return 50
    
    # All failed = 0
    if checks_passed == 0 and checks_failed > 0:
        return 0
    
    # All passed = 100
    if checks_failed == 0 and checks_passed > 0:
        return 100
    
    # Calculate based on pass rate, penalize failures more than skipped
    pass_rate = checks_passed / total_checks
    fail_rate = checks_failed / total_checks
    skip_rate = checks_skipped / total_checks
    
    # Weighted score: passes add, failures subtract (reduced for flaky test tolerance), skips slightly reduce
    score = (pass_rate * 100) - (fail_rate * 50) - (skip_rate * 20)
    
    return max(0, min(100, int(score)))


def calculate_pr_readiness(pr_data, review_classification, review_score):
    """
    Calculate overall PR readiness combining CI and review health
    
    Args:
        pr_data: Dict with PR info including CI checks
        review_classification: str from classify_review_health
        review_score: int from classify_review_health
    
    Returns:
        Dict with:
        {
            'overall_score': int 0-100,
            'ci_score': int 0-100,
            'review_score': int 0-100,
            'classification': str,
            'merge_ready': bool,
            'blockers': List[str],
            'warnings': List[str],
            'recommendations': List[str]
        }
    """
    # Calculate CI score
    ci_score = calculate_ci_confidence(
        pr_data.get('checks_passed', 0),
        pr_data.get('checks_failed', 0),
        pr_data.get('checks_skipped', 0)
    )
    
    # Weighted combination: 45% CI, 55% Review (reduced CI weight due to flaky tests)
    overall_score_raw = (ci_score * 0.45) + (review_score * 0.55)
    
    # Reduce readiness by 50% when changes are requested
    if review_classification == 'AWAITING_AUTHOR':
        overall_score_raw *= _CHANGES_REQUESTED_SCORE_MULTIPLIER
    
    # Reduce readiness by 33% when PR has merge conflicts.
    # Note: this multiplier compounds with other score multipliers (e.g. changes
    # requested), so a PR with both conditions would be scaled by
    # 0.5 * 0.67 = 0.335 (~66.5% total reduction).
    mergeable_state = pr_data.get('mergeable_state', '')
    if mergeable_state == 'dirty':
        overall_score_raw *= _MERGE_CONFLICTS_SCORE_MULTIPLIER
    
    overall_score = int(overall_score_raw)
    
    # Force score to 0% for Draft PRs
    is_draft = pr_data.get('is_draft') == 1 or pr_data.get('is_draft') == True
    if is_draft:
        overall_score = 0
    
    # Identify blockers, warnings, recommendations
    blockers = []
    warnings = []
    recommendations = []
    
    # Draft blocker
    if is_draft:
        blockers.append("PR is in draft mode")
        recommendations.append("Convert to 'Ready for review' when finished")
    
    # CI blockers (with tolerance for 1-2 flaky test failures)
    checks_failed = pr_data.get('checks_failed', 0)
    checks_skipped = pr_data.get('checks_skipped', 0)
    
    if checks_failed > 2:
        blockers.append(f"{checks_failed} CI check(s) failing")
        recommendations.append("Fix failing CI checks before merging")
    elif checks_failed > 0:
        warnings.append(f"{checks_failed} CI check(s) failing (possibly flaky tests)")
        recommendations.append("Verify if failures are from known flaky tests (Selenium, Docker)")
    
    if checks_skipped > 0:
        warnings.append(f"{checks_skipped} CI check(s) skipped")
    
    # Review blockers
    if review_classification == 'AWAITING_AUTHOR':
        blockers.append("Awaiting author response to feedback")
        recommendations.append("Address reviewer comments and push updates")
    
    if review_classification == 'STALLED':
        blockers.append("PR has stale unaddressed feedback")
        recommendations.append("Review and respond to old comments")
    
    if review_classification == 'NO_ACTIVITY':
        warnings.append("No review activity yet")
        recommendations.append("Request reviews from maintainers")
    
    if review_classification == 'AWAITING_REVIEWER':
        warnings.append("Awaiting reviewer approval")
        recommendations.append("Ping reviewers or request re-review")
    
    # PR state warnings
    if pr_data.get('state') == 'closed':
        blockers.append("PR is closed")
    
    if pr_data.get('is_merged') == 1:
        blockers.append("PR is already merged")
    
    mergeable_state = pr_data.get('mergeable_state', '')
    if mergeable_state == 'dirty':
        blockers.append("PR has merge conflicts")
        recommendations.append("Resolve merge conflicts with base branch")
    elif mergeable_state == 'blocked':
        warnings.append("PR is blocked by required status checks or reviews")
    
    # File change warnings
    files_changed = pr_data.get('files_changed', 0)
    if files_changed > 30:
        warnings.append(f"Large PR ({files_changed} files changed)")
        recommendations.append("Consider splitting into smaller PRs for easier review")
    
    # Determine if merge ready
    merge_ready = (
        overall_score >= 70 and
        len(blockers) == 0 and
        review_classification in ['APPROVED', 'AWAITING_REVIEWER', 'ACTIVE']
    )
    
    # Overall classification
    if merge_ready:
        classification = 'READY_TO_MERGE'
    elif overall_score >= 60:
        classification = 'NEARLY_READY'
    elif overall_score >= 40:
        classification = 'NEEDS_WORK'
    else:
        classification = 'NOT_READY'
    
    return {
        'overall_score': overall_score,
        'ci_score': ci_score,
        'review_score': review_score,
        'classification': classification,
        'merge_ready': merge_ready,
        'blockers': blockers,
        'warnings': warnings,
        'recommendations': recommendations
    }
