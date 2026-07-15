"""Aggregate API v1 routers."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routes import (
    admin_review,
    admin_review_workflow,
    admin_employer_verifications,
    admin_directory,
    admin_verification,
    auth,
    certifications,
    credential_verification,
    dashboard,
    documents,
    educations,
    employments,
    employment_documents,
    freelance_contracts,
    gig_platforms,
    health,
    internships,
    notifications,
    onboarding,
    organizations,
    passport,
    passport_shares,
    portfolio,
    verification_requests,
    trust_invitations,
    trust_registry,
    public_passport,
    public_credential_verification,
    public_employer_verification,
    public_employer_portal,
    public_profile,
    public_vault,
    trust_score,
    verification_connectors,
    user_documents,
    users,
    resumes,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(resumes.router)
api_router.include_router(dashboard.router)
api_router.include_router(onboarding.router)
api_router.include_router(organizations.router)
api_router.include_router(trust_invitations.org_router)
api_router.include_router(verification_requests.org_router)
api_router.include_router(employments.router)
api_router.include_router(public_employer_verification.router)
api_router.include_router(public_employer_portal.router)
api_router.include_router(public_profile.router)
api_router.include_router(public_passport.router)
api_router.include_router(public_vault.router)
api_router.include_router(credential_verification.router)
api_router.include_router(public_credential_verification.router)
api_router.include_router(documents.router)
api_router.include_router(employment_documents.router)
api_router.include_router(admin_review.router)
api_router.include_router(admin_review_workflow.router)
api_router.include_router(admin_employer_verifications.router)
api_router.include_router(admin_directory.router)
api_router.include_router(admin_verification.router)
api_router.include_router(notifications.admin_router)
api_router.include_router(verification_connectors.admin_router)
api_router.include_router(trust_registry.admin_router)
api_router.include_router(trust_registry.internal_router)
api_router.include_router(user_documents.router)
api_router.include_router(educations.router)
api_router.include_router(freelance_contracts.router)
api_router.include_router(internships.router)
api_router.include_router(gig_platforms.router)
api_router.include_router(passport.router)
api_router.include_router(passport_shares.router)
api_router.include_router(trust_invitations.router)
api_router.include_router(verification_requests.router)
api_router.include_router(portfolio.router)
api_router.include_router(certifications.router)
api_router.include_router(trust_score.router)
