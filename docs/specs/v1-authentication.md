# Spec: V1 Authentication

## Status

Completed

## Problem

The app needs basic login and role-aware protection before real treasurer data should be managed through the web interface.

## Scope

- Login page
- Logout flow
- Session-based authentication
- Route protection for admin pages
- Treasurer and secretary role checks
- Four internal admin accounts for handover and continuity
- Public forms remain accessible without login

## Acceptance criteria

- Unauthenticated users cannot access admin pages
- A seeded treasurer account can sign in
- A seeded admin, secretary, and helper account can also sign in
- Protected pages show the current signed-in user
- Logout clears the session cleanly
- `/forms` remains public while admin routes require login

## Deferred items

- Password reset
- Member self-service login
- Multi-factor authentication
