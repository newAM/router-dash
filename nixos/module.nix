{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.services.router-dash;
  settingsFormat = pkgs.formats.json {};
  configurationFile = settingsFormat.generate "router_dash_config.json" cfg.settings;
  gunicornConfigFile = pkgs.writeText "gunicorn.conf.py" ''
    accesslog = "-"
    access_log_format = "%(m)s %(U)s %(s)s %(b)s %(D)sµs"
    logger_class = "gunicorn.glogging.Logger"
    logconfig_dict = {
        "formatters": {
            "generic": {
                "format": "%(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "generic",
                "stream": "ext://sys.stdout",
            },
        },
        "root": {"level": "INFO", "handlers": ["console"]},
        "loggers": {
            "gunicorn.error": {
                "level": "INFO",
                "handlers": ["console"],
                "propagate": False,
                "qualname": "gunicorn.error",
            },
            "gunicorn.access": {
                "level": "INFO",
                "handlers": ["console"],
                "propagate": False,
                "qualname": "gunicorn.access",
            },
        },
    }
  '';
in {
  options.services.router-dash = {
    enable = lib.mkEnableOption "Router Dash DHCP lease dashboard";

    user = lib.mkOption {
      description = "User account under which router-dash runs.";
      type = lib.types.str;
      default = "router-dash";
    };

    group = lib.mkOption {
      description = "Group under which router-dash runs.";
      type = lib.types.str;
      default = "router-dash";
    };

    bindPath = lib.mkOption {
      description = "Path of the Unix domain socket to bind to.";
      type = lib.types.str;
      default = "/run/router-dash/router-dash.sock";
    };

    socketUser = lib.mkOption {
      description = "User that owns the Unix domain socket (e.g. a reverse proxy user).";
      type = lib.types.nullOr lib.types.str;
      default = null;
    };

    settings = lib.mkOption {
      type = lib.types.submodule {
        freeformType = lib.types.attrsOf settingsFormat.type;

        options = {
          SECRET_KEY_FILE = lib.mkOption {
            description = ''
              Path to a file containing the Flask secret key.

              This key is used to cryptographically sign session cookies.
              It must be kept secret and must not be stored in the Nix store.

              To generate a secure key:

              ```bash
              python3 -c "import secrets; print(secrets.token_hex())"
              ```
            '';
            type = lib.types.path;
            example = "/run/secrets/router_dash_secret_key";
          };

          KEA_API_URL = lib.mkOption {
            description = ''
              URL of the Kea DHCPv4 HTTP control socket
              (`control-sockets` with `socket-type = "http"`).

              Must point at the loopback interface.
            '';
            type = lib.types.str;
            default = "http://127.0.0.1:8000";
          };

          KEA_AUTH_USER_FILE = lib.mkOption {
            description = ''
              Path to a file containing the basic auth username for the
              Kea control socket.  Must match the Kea control socket
              `authentication.clients` configuration.
              Must not be stored in the Nix store.
            '';
            type = lib.types.nullOr lib.types.path;
            default = null;
            example = "/run/secrets/router_dash_kea_user";
          };

          KEA_AUTH_PASSWORD_FILE = lib.mkOption {
            description = ''
              Path to a file containing the basic auth password for the
              Kea control socket.
              Must not be stored in the Nix store.
            '';
            type = lib.types.nullOr lib.types.path;
            default = null;
            example = "/run/secrets/router_dash_kea_password";
          };

          OIDC_CLIENT_ID = lib.mkOption {
            description = "OIDC client ID registered with the identity provider.";
            type = lib.types.str;
          };

          OIDC_CLIENT_SECRET_FILE = lib.mkOption {
            description = ''
              Path to a file containing the OIDC client secret.
              Must not be stored in the Nix store.
            '';
            type = lib.types.path;
            example = "/run/secrets/router_dash_oidc_client_secret";
          };

          OIDC_DISCOVERY_URL = lib.mkOption {
            description = "OIDC discovery document URL for the identity provider.";
            example = "https://sso.example.com/.well-known/openid-configuration";
            type = lib.types.str;
          };

          PUBLIC_URL = lib.mkOption {
            description = "Public HTTPS base URL of the router-dash instance.";
            example = "https://router-dash.example.com";
            type = lib.types.str;
          };

          SESSION_FILE_DIR = lib.mkOption {
            description = "Directory for server-side session storage.";
            type = lib.types.path;
            default = "/var/lib/router-dash/sessions";
          };

          SESSION_COOKIE_SAMESITE = lib.mkOption {
            description = ''
              SameSite attribute for session cookies.

              - "Strict": cookie is only sent on same-site requests.
              - "Lax": cookie is also sent on top-level navigations from external sites.

              Use "Lax" if router-dash and the IdP are on different registrable
              domains.
            '';
            type = lib.types.enum ["Strict" "Lax"];
            default = "Strict";
          };

          ROLES_PATH = lib.mkOption {
            description = ''
              JSON path within the OIDC access token or userinfo claims to
              a list of role strings.

              Example for Keycloak:
                ["resource_access" "router-dash" "roles"]
              Example for Kanidm:
                ["router_dash_roles"]
            '';
            type = lib.types.listOf lib.types.str;
          };

          VIEWER_ROLE = lib.mkOption {
            description = ''
              Role name that grants access to the dashboard.
              Users must have this role in their OIDC token to view leases.
            '';
            type = lib.types.str;
            default = "router_dash_users";
          };

          LOG_LEVEL = lib.mkOption {
            description = "Logging level for the router-dash application.";
            type = lib.types.enum ["DEBUG" "INFO" "WARNING" "ERROR" "CRITICAL"];
            default = "WARNING";
          };
        };
      };
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion =
          (cfg.settings.KEA_AUTH_USER_FILE == null)
          == (cfg.settings.KEA_AUTH_PASSWORD_FILE == null);
        message = "services.router-dash.settings.KEA_AUTH_USER_FILE and KEA_AUTH_PASSWORD_FILE must be set together";
      }
    ];

    users.users.${cfg.user} = lib.mkIf (cfg.user == "router-dash") {
      isSystemUser = true;
      group = cfg.group;
      description = "Router Dash service user";
    };

    users.groups.${cfg.group} = lib.mkIf (cfg.group == "router-dash") {};

    systemd.sockets.router-dash = {
      description = "Router Dash service socket";
      wantedBy = ["sockets.target"];
      listenStreams = [cfg.bindPath];
      socketConfig = {
        SocketMode = "0660";
        SocketUser = cfg.socketUser;
        RemoveOnStop = true;
        FlushPending = true;
      };
    };

    systemd.services.router-dash = {
      description = "Router Dash DHCP lease dashboard";
      wantedBy = ["multi-user.target"];
      bindsTo = ["router-dash.socket"];
      after = ["router-dash.socket"];

      environment = {
        ROUTER_DASH_CONFIG_FILE = "${configurationFile}";
        # Use the NixOS system CA bundle so that self-signed or private CA
        # certificates trusted via security.pki.certificateFiles are also
        # trusted by Python's ssl module and the requests library.
        SSL_CERT_FILE = "/etc/ssl/certs/ca-bundle.crt";
        REQUESTS_CA_BUNDLE = "/etc/ssl/certs/ca-bundle.crt";
      };

      serviceConfig = {
        ExecStart = "${lib.getExe' pkgs.router-dash "gunicorn"} --config ${gunicornConfigFile} --bind unix:${cfg.bindPath} router_dash.wsgi:application";
        User = cfg.user;
        Group = cfg.group;
        Restart = "on-failure";
        RestartSec = 10;
        Type = "idle";
        KillSignal = "SIGINT";

        # State directory for server-side sessions
        StateDirectory = "router-dash";
        StateDirectoryMode = "0700";

        # Hardening
        DevicePolicy = "closed";
        CapabilityBoundingSet = "";
        RestrictAddressFamilies = ["AF_UNIX" "AF_INET" "AF_INET6"];
        DeviceAllow = "";
        NoNewPrivileges = true;
        PrivateDevices = true;
        PrivateMounts = true;
        PrivateTmp = true;
        PrivateUsers = true;
        ProtectClock = true;
        ProtectControlGroups = true;
        ProtectHome = true;
        ProtectKernelLogs = true;
        ProtectKernelModules = true;
        ProtectKernelTunables = true;
        ProtectSystem = "strict";
        MemoryDenyWriteExecute = true;
        LockPersonality = true;
        RemoveIPC = true;
        RestrictNamespaces = true;
        RestrictRealtime = true;
        RestrictSUIDSGID = true;
        SystemCallArchitectures = "native";
        SystemCallFilter = [
          "@system-service"
          "~@privileged"
          "~@resources"
        ];
        ProtectProc = "invisible";
        ProtectHostname = true;
        ProcSubset = "pid";
        UMask = "0077";
      };
    };
  };

  meta.maintainers = pkgs.router-dash.meta.maintainers;
}
