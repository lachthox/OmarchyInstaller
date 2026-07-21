# Run only from a real interactive login shell; the Python policy revalidates all conditions.
if [[ $- == *i* ]] && [[ -t 0 && -t 1 ]] && [[ ${EUID:-0} -ne 0 ]] \
  && [[ -f /var/lib/omarchy/install/install-success.json ]] \
  && [[ ! -f "${XDG_STATE_HOME:-$HOME/.local/state}/omarchy-installer/state.json" ]]; then
  /usr/local/bin/omarchy-first-login
fi
