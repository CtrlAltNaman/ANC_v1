idf_component_register(SRCS "main.c" "clip.c" "web.c"
                    PRIV_REQUIRES driver esp_wifi esp_http_server esp_netif
                                  esp_event nvs_flash esp_timer
                    INCLUDE_DIRS ".")
