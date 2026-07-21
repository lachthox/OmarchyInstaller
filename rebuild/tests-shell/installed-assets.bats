#!/usr/bin/env bats

@test "live launcher enters the Python module" {
  run grep -F "python -m installer.main" rebuild/assets/scripts/live-autostart.sh
  [ "$status" -eq 0 ]
}

@test "first-login launcher enters the Python module" {
  run grep -F "python -m installer.platforms.installed_system.first_login" rebuild/assets/scripts/first-login.sh
  [ "$status" -eq 0 ]
}

@test "first-login hook requires a normal user" {
  run grep -F '[[ "$EUID" -ne 0 ]]' rebuild/assets/scripts/first-login-profile.sh
  [ "$status" -eq 0 ]
}

@test "guardian records successful completion" {
  run grep -F "record-success" rebuild/assets/services/boot-guardian.service
  [ "$status" -eq 0 ]
}
