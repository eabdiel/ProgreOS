#pragma once

#include "esp_err.h"

esp_err_t progre_display_init(void);
void progre_display_draw_first_light(void);
void progre_display_set_blink(bool closed);
