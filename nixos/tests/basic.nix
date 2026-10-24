{
  self,
  pkgs,
}: let
  routerDashDomain = "router-dash.home.arpa";
  kanidmDomain = "kanidm.home.arpa";
  nginxPort = 10443;
  kanidmPort = 20443;
  keaApiPort = 8000;
  kanidmFrontendUrl = "https://${kanidmDomain}:${toString kanidmPort}";
  routerDashUrl = "https://${routerDashDomain}:${toString nginxPort}";

  SECRET_KEY_FILE = "/run/router_dash_secret_key";
  # Basic auth credentials for the Kea control socket, shared by Kea
  # (via its authentication.clients config) and the dashboard.
  keaAuthUser = "router-dash";
  keaAuthPassword = "test-kea-api-password";
  keaAuthDir = "/run/kea-api-auth";
  keaUserFile = "${keaAuthDir}/user";
  keaPasswordFile = "${keaAuthDir}/password";
  # Separate copies so each service only reads its own files.
  appKeaAuthDir = "/run/router-dash-kea-auth";
  appKeaUserFile = "${appKeaAuthDir}/user";
  appKeaPasswordFile = "${appKeaAuthDir}/password";

  oidcClientId = "router-dash";
  oidcClientSecretFile = pkgs.writeText "router_dash_oidc_client_secret" "test-oidc-client-secret";
  oidcDiscoveryUrl = "${kanidmFrontendUrl}/oauth2/openid/${oidcClientId}/.well-known/openid-configuration";

  # Kea serves DHCPv4 on the second test VLAN (192.168.2.0/24).
  dhcpSubnet = "192.168.2.0/24";
  dhcpClientIp = "192.168.2.100";

  kanidmUsername = "testuser";
in
  pkgs.testers.nixosTest {
    name = "router-dash-basic";

    nodes.server = {config, ...}: {
      imports = [self.nixosModules.default];
      nixpkgs.overlays = [self.overlays.default];

      virtualisation.vlans = [1 2];

      networking.hosts."127.0.0.1" = [routerDashDomain kanidmDomain];
      networking.firewall.allowedTCPPorts = [nginxPort kanidmPort];

      # Kea DHCPv4 server with an authenticated HTTP control socket on
      # the loopback interface.
      services.kea.dhcp4 = {
        enable = true;
        settings = {
          # The test framework names the second VLAN interface "eth2".
          interfaces-config.interfaces = ["eth2"];
          # lease4-get-all is provided by the lease_cmds hook library.
          hooks-libraries = [
            {library = "${pkgs.kea}/lib/kea/hooks/libdhcp_lease_cmds.so";}
          ];
          lease-database = {
            type = "memfile";
            persist = false;
          };
          subnet4 = [
            {
              id = 1;
              subnet = dhcpSubnet;
              pools = [{pool = "192.168.2.100 - 192.168.2.200";}];
              valid-lifetime = 3600;
            }
          ];
          control-sockets = [
            {
              socket-type = "http";
              socket-address = "127.0.0.1";
              socket-port = keaApiPort;
              authentication = {
                type = "basic";
                realm = "kea-control";
                clients = [
                  {
                    user-file = keaUserFile;
                    password-file = keaPasswordFile;
                  }
                ];
              };
            }
          ];
        };
      };

      # Provision the Kea control socket credentials before Kea starts.
      systemd.services.kea-api-auth = {
        description = "Write Kea control socket basic auth credentials";
        wantedBy = ["kea-dhcp4-server.service" "router-dash.service"];
        before = ["kea-dhcp4-server.service" "router-dash.service"];
        script = ''
          mkdir -p ${keaAuthDir} ${appKeaAuthDir}
          printf '%s' '${keaAuthUser}' > ${keaUserFile}
          printf '%s' '${keaAuthPassword}' > ${keaPasswordFile}
          chmod 400 ${keaUserFile} ${keaPasswordFile}
          chown kea:kea ${keaUserFile} ${keaPasswordFile}
          printf '%s' '${keaAuthUser}' > ${appKeaUserFile}
          printf '%s' '${keaAuthPassword}' > ${appKeaPasswordFile}
          chmod 400 ${appKeaUserFile} ${appKeaPasswordFile}
          chown router-dash:router-dash ${appKeaUserFile} ${appKeaPasswordFile}
        '';
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
        };
      };

      # kanidm identity provider
      services.kanidm = {
        package = pkgs.kanidmWithSecretProvisioning_1_11;
        server = {
          enable = true;
          settings = {
            version = "2";
            bindaddress = "0.0.0.0:${toString kanidmPort}";
            domain = kanidmDomain;
            origin = kanidmFrontendUrl;
            tls_chain = ./kanidm.home.arpa.cert.pem;
            tls_key = ./kanidm.home.arpa.key.pem;
          };
        };
        client = {
          enable = true;
          settings = {
            uri = kanidmFrontendUrl;
            verify_ca = true;
            verify_hostnames = true;
          };
        };
        provision = {
          enable = true;
          systems.oauth2.${oidcClientId} = {
            displayName = "Router Dash";
            public = false;
            enableLegacyCrypto = false;
            preferShortUsername = true;
            basicSecretFile = oidcClientSecretFile;
            originUrl = "${routerDashUrl}/auth/callback";
            originLanding = routerDashUrl;
            scopeMaps."router_dash_users" = ["openid" "email" "profile"];
            # A group with basic SSO scopes but no router_dash_roles claim,
            # to exercise the application's role check end-to-end.
            scopeMaps."idp_users" = ["openid" "email" "profile"];
            removeOrphanedClaimMaps = true;
            claimMaps."router_dash_roles".valuesByGroup."router_dash_users" = ["router_dash_users"];
          };
          persons.${kanidmUsername} = {
            displayName = "Test User";
            mailAddresses = ["testuser@example.com"];
          };
          persons.intruder = {
            displayName = "Intruder";
            mailAddresses = ["intruder@example.com"];
          };
          groups."router_dash_users".members = [kanidmUsername];
          groups."idp_users".members = ["intruder"];
        };
      };

      # router-dash application
      services.router-dash = {
        enable = true;
        socketUser = config.services.nginx.user;
        settings = {
          inherit SECRET_KEY_FILE;
          KEA_API_URL = "http://127.0.0.1:${toString keaApiPort}";
          KEA_AUTH_USER_FILE = appKeaUserFile;
          KEA_AUTH_PASSWORD_FILE = appKeaPasswordFile;
          OIDC_CLIENT_SECRET_FILE = toString oidcClientSecretFile;
          OIDC_CLIENT_ID = oidcClientId;
          OIDC_DISCOVERY_URL = oidcDiscoveryUrl;
          PUBLIC_URL = routerDashUrl;
          # .arpa is on the public suffix list, so the browser treats
          # router-dash.home.arpa and kanidm.home.arpa as cross-site.
          # Use Lax so the IdP callback redirect carries the session cookie.
          SESSION_COOKIE_SAMESITE = "Lax";
          ROLES_PATH = ["router_dash_roles"];
        };
      };

      services.nginx = {
        enable = true;
        defaultSSLListenPort = nginxPort;
        virtualHosts.${routerDashDomain} = {
          onlySSL = true;
          sslCertificate = ./router-dash.home.arpa.cert.pem;
          sslCertificateKey = ./router-dash.home.arpa.key.pem;
          locations."/".proxyPass = "http://unix:${config.services.router-dash.bindPath}";
        };
      };

      security.pki.certificateFiles = [
        ./router-dash.home.arpa.cert.pem
        ./kanidm.home.arpa.cert.pem
      ];

      # Write the Flask secret key before router-dash starts
      systemd.services.router-dash-test-secret = {
        description = "Write test secret key for router-dash";
        wantedBy = ["router-dash.service"];
        before = ["router-dash.service"];
        script = ''
          echo test-secret-key-do-not-use-in-production > ${SECRET_KEY_FILE}
          chmod 600 ${SECRET_KEY_FILE}
          chown router-dash:router-dash ${SECRET_KEY_FILE}
        '';
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
        };
      };

      environment.systemPackages = with pkgs; [
        curl
        htmlq
      ];
    };

    nodes.client = {config, ...}: {
      virtualisation.vlans = [1 2];
      networking.hostName = "testclient";
      environment.systemPackages = [pkgs.dhcpcd];
    };

    testScript = ''
      import json

      def get_csrf(server, path: str) -> str:
        server.succeed(
            "curl -sSf -b cookies.txt -o csrf.html ${routerDashUrl}" + path,
            "htmlq 'input[name=csrf_token]' --attribute value --filename csrf.html --output csrf.txt",
        )
        return server.succeed("head -1 csrf.txt").rstrip()

      def oidc_login(server, username: str, password: str, app_cookies: str, sso_cookies: str) -> None:
        """Complete the full OIDC authorization code flow via curl."""
        sso_login_url: str = server.succeed(
          f"curl -sSf -c {app_cookies} -w %{{redirect_url}} -o /dev/null ${routerDashUrl}/login"
        ).rstrip()
        print(f"{sso_login_url=}")

        # fetch the username form page
        server.succeed(
          f"curl -sSf -c {sso_cookies} -o login_page.html '{sso_login_url}'",
          "htmlq '#login' --attribute action --filename login_page.html --output username_form_action.txt",
        )
        username_post_url: str = "${kanidmFrontendUrl}" + server.succeed("cat username_form_action.txt").rstrip()

        # post username, get the password form page
        server.succeed(
          f"curl -sSf -b {sso_cookies} -c {sso_cookies} -o password_page.html"
          f" -d 'username={username}' -d 'password=' -d 'totp='"
          f" '{username_post_url}'",
          "htmlq '#login' --attribute action --filename password_page.html --output password_form_action.txt",
        )
        password_post_url: str = "${kanidmFrontendUrl}" + server.succeed("cat password_form_action.txt").rstrip()

        # post password, get resume session redirect
        resume_url: str = server.succeed(
          f"curl -sSf -b {sso_cookies} -c {sso_cookies} -w %{{redirect_url}} -o /dev/null"
          f" -d 'password={password}' '{password_post_url}'"
        ).rstrip()
        assert resume_url.startswith("https://"), f"invalid resume URL: {resume_url!r}"

        # follow resume url, get consent page
        server.succeed(
          f"curl -sSf -b {sso_cookies} -c {sso_cookies} -o consent_page.html '{resume_url}'",
          "htmlq '#login' --attribute action --filename consent_page.html --output consent_form_action.txt",
          "htmlq '#consent_token' --attribute value --filename consent_page.html --output consent_token.txt",
        )
        consent_post_url: str = "${kanidmFrontendUrl}" + server.succeed("cat consent_form_action.txt").rstrip()
        consent_token: str = server.succeed("cat consent_token.txt").rstrip()

        # post consent, get callback redirect back to router-dash
        callback_url: str = server.succeed(
          f"curl -sSf -b {sso_cookies} -c {sso_cookies} -w %{{redirect_url}} -o /dev/null"
          f" -d 'consent_token={consent_token}' '{consent_post_url}'"
        ).rstrip()

        # follow the callback - establishes the router-dash session.
        # No -f: the landing page may legitimately return an error page
        # (e.g. 403 for a user without the required role).
        server.succeed(
          f"curl -L -sS -b {app_cookies} -c {app_cookies} -o /dev/null '{callback_url}'"
        )

      start_all()

      server.wait_for_unit("kanidm.service")
      server.wait_for_open_port(${toString kanidmPort})
      server.wait_until_succeeds("curl -sSf ${kanidmFrontendUrl}")

      server.wait_for_unit("kea-dhcp4-server.service")
      server.wait_for_open_port(${toString keaApiPort}, "127.0.0.1")
      server.wait_for_unit("router-dash.socket")
      server.wait_for_unit("router-dash.service")
      server.wait_for_unit("nginx.service")

      # recover a password for the test user
      pw = server.succeed(
        "kanidmd recover-account ${kanidmUsername} 2>&1 | grep -oP '[A-Za-z0-9]{48}'"
      ).strip()
      intruder_pw = server.succeed(
        "kanidmd recover-account intruder 2>&1 | grep -oP '[A-Za-z0-9]{48}'"
      ).strip()

      # Obtain a real DHCP lease from Kea for the client's second interface
      # (the test framework names it "eth2").
      client.succeed("dhcpcd --oneshot eth2 2>&1")
      client.wait_until_succeeds("ip -4 addr show dev eth2 | grep ${dhcpClientIp}")
      client_mac = client.succeed("cat /sys/class/net/eth2/address").strip()

      with subtest("Kea control socket requires authentication"):
        status = server.succeed(
          "curl -s -o /dev/null -w '%{http_code}'"
          " -H 'Content-Type: application/json'"
          " -d '{\"command\": \"version-get\"}' http://127.0.0.1:${toString keaApiPort}/"
        ).strip()
        assert status == "401", f"expected 401 without credentials, got: {status}"

      with subtest("Health check"):
        response = server.succeed("curl -sf ${routerDashUrl}/healthz")
        data = json.loads(response)
        assert data == {"status": "ok"}, f"unexpected response: {data}"

      with subtest("Security headers"):
        headers = server.succeed("curl -sI ${routerDashUrl}/healthz")
        assert "content-security-policy: default-src 'none'" in headers.lower(), headers
        assert "strict-transport-security" in headers.lower(), headers
        assert "x-frame-options: deny" in headers.lower(), headers
        assert "cache-control: no-store" in headers.lower(), headers

      with subtest("Unauthenticated access redirects to login"):
        redirect = server.succeed(
          "curl -s -o /dev/null -w '%{redirect_url}' ${routerDashUrl}/"
        ).rstrip()
        assert "/login" in redirect, f"expected login redirect, got: {redirect}"

      with subtest("Login and view leases"):
        oidc_login(server, "${kanidmUsername}", pw, "cookies.txt", "sso_cookies.txt")

        dashboard = server.succeed("curl -sSf -b cookies.txt ${routerDashUrl}/")
        assert "testclient" in dashboard, "client hostname not in lease table"
        assert "${dhcpClientIp}" in dashboard, "client IP not in lease table"
        assert client_mac in dashboard, f"client MAC ({client_mac}) not in lease table"

        # Table is sortable: canonical sort values and header buttons exist.
        assert "table class=\"sortable\"" in dashboard, "sortable table missing"
        assert "data-v=" in dashboard, "sort values missing"
        assert "aria-sort" in dashboard, "aria-sort missing"

      with subtest("Static assets"):
        server.succeed("curl -sSf ${routerDashUrl}/static/style.css -o /dev/null")
        js = server.succeed("curl -sSf ${routerDashUrl}/static/sort.js")
        assert "enableSorting" in js, "sorting script missing"

      with subtest("User without the required role is denied"):
        oidc_login(server, "intruder", intruder_pw, "intruder_cookies.txt", "intruder_sso_cookies.txt")
        status = server.succeed(
          "curl -s -o intruder.html -w '%{http_code}' -b intruder_cookies.txt ${routerDashUrl}/"
        ).strip()
        assert status == "403", f"expected 403 for roleless user, got: {status}"
        intruder_page = server.succeed("cat intruder.html")
        assert "router_dash_users" in intruder_page, "role name not in denial message"

      with subtest("Logout"):
        csrf_token: str = get_csrf(server, "/")

        final_url: str = server.succeed(
          f"curl -sSf -L -b cookies.txt -c cookies.txt -o /dev/null -w '%{{url_effective}}' -F 'csrf_token={csrf_token}' ${routerDashUrl}/logout",
        ).rstrip()
        assert "/logged-out" in final_url, f"expected /logged-out, got: {final_url}"

        # verify session is cleared, / should redirect to /login again
        redirect_after_logout: str = server.succeed(
          "curl -sSf -b cookies.txt -o /dev/null -w %{redirect_url} ${routerDashUrl}/"
        ).rstrip()
        assert "login" in redirect_after_logout, f"expected login redirect, got: {redirect_after_logout}"

      with subtest("Logout without CSRF token is rejected"):
        status = server.succeed(
          "curl -s -o /dev/null -w '%{http_code}' -b cookies.txt -X POST ${routerDashUrl}/logout"
        ).strip()
        assert status == "400", f"expected 400 without CSRF token, got: {status}"
    '';
  }
