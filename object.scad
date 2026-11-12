// =========================================================================
// BABY BUDDY LOGGER - SNAP-FIT ENCLOSURE WITH LIPO & BACKPACK CRADLES
// =========================================================================

/* [Render Selection] */
render_mode = "knob"; // ["all", "base", "lid", "knob"]

/* [Enclosure Dimensions] */
box_length  = 105;    // X-axis width (mm)
box_width   = 56;     // Y-axis depth (mm)
base_height = 30;     // 8mm subfloor for LiPo + 22mm upper bay for Pico & DuPont wires
lid_height  = 12;     // Top faceplate skirt height (mm)
wall_thick  = 2.4;    // 3 perimeters with a 0.4mm nozzle
corner_rad  = 4.0;

/* [Battery & Charger Dimensions] */
// Adafruit 2500mAh LiPo (328) is 61 x 47 x 6.7mm -> 62.5 x 48.2mm pocket
lipo_length = 62.5;
lipo_width  = 48.2;
lipo_thick  = 7.5;    // Height of battery subfloor bay

// Adafruit LiIon/LiPoly Backpack (#2124) is 15.0 x 17.0mm PCB
backpack_w  = 15.5;   // X-dimension in cradle
backpack_l  = 17.5;   // Y-dimension in cradle

/* [Component Dimensions & Tolerances] */

/* [Updated KS0013 Encoder Cradle Parameters - No Pegs Needed] */
ks0013_shaft_dia     = 7.2;   // Snug fit for the 7mm threaded bushing
ks0013_pcb_l         = 26.5;  // Length of PCB from front edge to 5-pin header edge (X-axis)
ks0013_pcb_w         = 19.2;  // Width of PCB across the top/bottom edges (Y-axis)
ks0013_shaft_from_back = 10.5;// Distance from center of shaft to the non-header edge of PCB
ks0013_standoff_h    = 5.5;   // Depth from inside lid ceiling to PCB face
ks0013_pcb_thick     = 1.7;   // 1.6mm PCB thickness + 0.1mm clearance

// 0.96" SSD1306 I2C OLED (4-pin)
oled_window_w   = 26.0;
oled_window_h   = 15.0;
oled_pcb_w      = 27.5;
oled_pcb_h      = 28.0;
oled_mount_x    = 23.0;
oled_mount_y    = 23.5;
oled_standoff_h = 3.5;

// Raspberry Pi Pico W
pico_length = 51.5;
pico_width  = 21.5;
pico_hole_x = 47.0;
pico_hole_y = 11.4;

// Sleek Low-Profile Knurled D-Shaft Knob (24x14mm)
knob_outer_dia  = 24.0;
knob_height     = 14.0;
knob_skirt_h    = 3.0;
knob_skirt_dia  = 20.0;
shaft_dia       = 6.1;
shaft_flat_thk  = 4.6;
shaft_depth     = 11.0;

$fn = 60;

// =========================================================================
// MAIN RENDER CONTROLLER
// =========================================================================
if (render_mode == "all") {
    bottom_base();
    translate([0, box_width + 12, lid_height])
        rotate([180, 0, 0])
            top_lid();
    translate([box_length + 22, box_width / 2, 0])
        encoder_knob();
} else if (render_mode == "base") {
    bottom_base();
} else if (render_mode == "lid") {
    translate([0, 0, lid_height])
        rotate([180, 0, 0])
            top_lid();
} else if (render_mode == "knob") {
    encoder_knob();
}

// =========================================================================
// 1. BOTTOM BASE (Floor LiPo Tray + Elevated Pico W & Backpack Cradles)
// =========================================================================
module bottom_base() {
    pico_origin_x = wall_thick + 1.5;
    pico_origin_y = (box_width - pico_width) / 2;
    // Elevate Pico above the 7.5mm LiPo battery bay
    pico_deck_z   = wall_thick + lipo_thick + 2.0;

    // Position the 62.5 x 48.2mm LiPo tray on the right/center floor
    lipo_x = box_length - wall_thick - lipo_length - 2.0;
    lipo_y = (box_width - lipo_width) / 2;

    difference() {
        rounded_box(box_length, box_width, base_height, corner_rad);

        // Hollow main interior
        translate([wall_thick, wall_thick, wall_thick])
            rounded_box(
                box_length - 2*wall_thick,
                box_width - 2*wall_thick,
                base_height,
                corner_rad - wall_thick/2
            );

        // Micro-USB cutout on left wall (aligned with elevated Pico deck)
        translate([-0.5, box_width/2 - 5.5, pico_deck_z - 1.0])
            cube([wall_thick + 2, 11, 7.5]);
        translate([-0.5, box_width/2 - 7.5, pico_deck_z - 2.5])
            cube([1.4, 15, 10.5]);

        // Front & Back Internal Snap-Catch Grooves (4x catches)
        for (x_pos = [26, box_length - 26]) {
            translate([x_pos - 7, wall_thick - 0.9, base_height - 4.2])
                cube([14, 1.2, 2.4]);
            translate([x_pos - 7, box_width - wall_thick - 0.3, base_height - 4.2])
                cube([14, 1.2, 2.4]);
        }

        // Pry notch on right seam
        translate([box_length - 1.2, box_width/2 - 6, base_height - 1.2])
            cube([2.0, 12, 1.5]);
    }

    // --- A. FLOOR TRAY FOR ADAFRUIT 3.7V 2500mAh LIPO (61 x 47 x 6.7mm) ---
    // Left & Right perimeter rails on the floor to frame the LiPo pouch
    translate([lipo_x - 1.6, lipo_y, wall_thick])
        cube([1.6, lipo_width, lipo_thick]);
    translate([lipo_x + lipo_length, lipo_y, wall_thick]) {
        cube([1.6, lipo_width, lipo_thick]);
        // Snap-over lip on right edge to keep battery flat without tape
        translate([-1.0, lipo_width/2 - 10, lipo_thick - 0.5])
            cube([2.6, 20, 1.2]);
    }

    // --- B. ELEVATED PICO W MOUNTING TOWERS (Clears LiPo Underneath) ---
    for (dx = [2.0, 2.0 + pico_hole_x]) {
        for (dy = [(pico_width - pico_hole_y)/2, (pico_width + pico_hole_y)/2]) {
            translate([pico_origin_x + dx, pico_origin_y + dy, wall_thick]) {
                cylinder(d=5.2, h=pico_deck_z - wall_thick);  // Support column
                cylinder(d=1.9, h=pico_deck_z - wall_thick + 2.8); // Press-fit pin
            }
        }
    }
    // Snap-latch tab at right end of Pico W
    translate([pico_origin_x + pico_length, box_width/2 - 4, wall_thick]) {
        cube([1.8, 8, pico_deck_z - wall_thick + 1.8]);
        translate([-0.5, 0, pico_deck_z - wall_thick + 1.6])
            cube([2.3, 8, 1.0]);
    }

    // --- C. ADAFRUIT BACKPACK CHARGER CRADLE (#2124 - 15 x 17mm) ---
    // Mounted on a pedestal right next to the Pico's top-right pins (VBUS/VSYS/GND)
    bp_x = pico_origin_x + pico_length + 5.0;
    bp_y = box_width - wall_thick - backpack_l - 2.5;

    translate([bp_x, bp_y, wall_thick + lipo_thick]) {
        // Supporting bridge bar across the top of the LiPo bay
        translate([-2.0, -1.5, 0])
            cube([backpack_w + 4.0, backpack_l + 3.0, 2.0]);

        // 4-sided snap pocket for the 15x17mm Backpack PCB
        difference() {
            translate([-1.2, -1.2, 2.0])
                cube([backpack_w + 2.4, backpack_l + 2.4, 3.5]);
            translate([0, 0, 1.9])
                cube([backpack_w, backpack_l, 4.0]);
            // Cutout on front edge for the 2-pin JST battery jack
            translate([backpack_w/2 - 4.5, -2.0, 1.9])
                cube([9.0, 4.0, 4.0]);
        }
    }
}

// =========================================================================
// 2. TOP LID (Nut-Free Snap-In KS0013 Cage + Press-Fit OLED)
// =========================================================================
module top_lid() {
    oled_cx = 34;
    oled_cy = box_width / 2;

    enc_cx  = 78;
    enc_cy  = box_width / 2;

    ceiling_z = lid_height - wall_thick;

    difference() {
        union() {
            rounded_box(box_length, box_width, lid_height, corner_rad);

            lip_clearance = 0.25;
            translate([
                wall_thick + lip_clearance,
                wall_thick + lip_clearance,
                -2.2
            ])
                rounded_box(
                    box_length - 2*(wall_thick + lip_clearance),
                    box_width - 2*(wall_thick + lip_clearance),
                    2.5,
                    corner_rad - wall_thick
                );
        }

        translate([wall_thick + 1.6, wall_thick + 1.6, -3.0])
            rounded_box(
                box_length - 2*(wall_thick + 1.6),
                box_width - 2*(wall_thick + 1.6),
                lid_height + 3.0 - wall_thick,
                corner_rad - wall_thick
            );

        // 1. SSD1306 OLED Viewport Cutout
        translate([oled_cx - oled_window_w/2, oled_cy - oled_window_h/2, ceiling_z - 0.5])
            cube([oled_window_w, oled_window_h, wall_thick + 1]);

        // 2. KS0013 Rotary Encoder Snug Bushing Hole
        translate([enc_cx, enc_cy, ceiling_z - 0.5])
            cylinder(d=ks0013_shaft_dia, h=wall_thick + 1);
    }

    // A. 4x Cantilever Case Snap-Fit Tabs (Front & Back Edges)
    for (x_pos = [26, box_length - 26]) {
        translate([x_pos - 5, wall_thick + 0.25, -4.2]) {
            cube([10, 1.4, 5.0]);
            translate([0, -0.6, 0.4])
                cube([10, 2.0, 1.4]);
        }
        translate([x_pos - 5, box_width - wall_thick - 1.65, -4.2]) {
            cube([10, 1.4, 5.0]);
            translate([0, 0, 0.4])
                cube([10, 2.0, 1.4]);
        }
    }

    // B. Peg-Free KS0013 Perimeter Cradle + Snap Latches
    // Calculates PCB bounding box relative to the shaft center (enc_cx, enc_cy)
    // Oriented so the 5-pin header faces Left (-X) toward the Pico W
    pcb_min_x = enc_cx - (ks0013_pcb_l - ks0013_shaft_from_back);
    pcb_min_y = enc_cy - ks0013_pcb_w / 2;

    // 1. Four flat backing ledges at the corners of the PCB (supports knob clicks)
    for (cx = [pcb_min_x, pcb_min_x + ks0013_pcb_l - 5.0]) {
        for (cy = [pcb_min_y, pcb_min_y + ks0013_pcb_w - 4.0]) {
            translate([cx, cy, ceiling_z - ks0013_standoff_h])
                cube([5.0, 4.0, ks0013_standoff_h]);
        }
    }

    // 2. Anti-rotation guide walls along Top (+Y), Bottom (-Y), and Right (+X) edges
    wall_h = ks0013_standoff_h + ks0013_pcb_thick;
    // Right-hand backstop wall
    translate([pcb_min_x + ks0013_pcb_l, pcb_min_y - 1.2, ceiling_z - wall_h])
        cube([1.6, ks0013_pcb_w + 2.4, wall_h]);

    // 3. Top & Bottom Cantilever Snap Hooks (Grips outer PCB edges, no holes used!)
    clip_total_h = ks0013_standoff_h + ks0013_pcb_thick + 1.2;
    for (dir = [-1, 1]) {
        clip_y = enc_cy + dir * (ks0013_pcb_w / 2 + 0.8) - 0.8;
        translate([enc_cx - 5.0, clip_y, ceiling_z - clip_total_h]) {
            // Flexible vertical arm + anti-rotation side wall
            cube([10.0, 1.6, clip_total_h]);
            // Snap barb with 45-degree lead-in ramp that hooks over the back of the PCB
            translate([0, dir * -0.7, 0])
                cube([10.0, 1.6, 1.1]);
        }
    }

    // C. Screwless SSD1306 OLED Press-Fit Pins + Side Snap Clips
    for (dx = [-oled_mount_x/2, oled_mount_x/2]) {
        for (dy = [-oled_mount_y/2, oled_mount_y/2]) {
            translate([oled_cx + dx, oled_cy + dy, ceiling_z - oled_standoff_h]) {
                cylinder(d=4.4, h=oled_standoff_h);
                translate([0, 0, -2.2])
                    cylinder(d=1.85, h=2.2);
            }
        }
    }
    for (side = [-1, 1]) {
        clip_x = oled_cx + side * (oled_pcb_w/2 + 0.8) - 0.8;
        translate([clip_x, oled_cy - 5, ceiling_z - oled_standoff_h - 2.6]) {
            cube([1.6, 10, oled_standoff_h + 2.6]);
            translate([side * -0.6, 0, 0])
                cube([1.6, 10, 1.0]);
        }
    }
}
// =========================================================================
// 3. KNURLED D-SHAFT KNOB (24 x 14mm Low-Profile)
// =========================================================================
module encoder_knob() {
    knurls_count = 36;
    knurl_depth  = 1.0;

    difference() {
        union() {
            cylinder(d=knob_skirt_dia, h=knob_skirt_h);
            translate([0, 0, knob_skirt_h])
                cylinder(d=knob_outer_dia - knurl_depth, h=knob_height - knob_skirt_h);

            for (i = [0 : knurls_count - 1]) {
                rotate([0, 0, i * (360 / knurls_count)])
                    translate([knob_outer_dia / 2 - knurl_depth / 2, 0, knob_skirt_h + (knob_height - knob_skirt_h)/2])
                        rotate([0, 0, 45])
                            cube([knurl_depth * 1.4, knurl_depth * 1.4, knob_height - knob_skirt_h], center=true);
            }
        }

        // D-Shaft socket
        translate([0, 0, -0.1]) {
            intersection() {
                cylinder(d=shaft_dia, h=shaft_depth + 0.1);
                translate([-shaft_dia/2, -shaft_dia + shaft_flat_thk, 0])
                    cube([shaft_dia, shaft_dia, shaft_depth + 0.2]);
            }
        }

        
    }
}

// =========================================================================
// HELPER MODULE
// =========================================================================
module rounded_box(l, w, h, r) {
    hull() {
        translate([r, r, 0])         cylinder(r=r, h=h);
        translate([l - r, r, 0])     cylinder(r=r, h=h);
        translate([r, w - r, 0])     cylinder(r=r, h=h);
        translate([l - r, w - r, 0]) cylinder(r=r, h=h);
    }
}