// =========================================================================
// BABY BUDDY LOGGER - FREESTANDING PICO POSTS & DEEP-TAPPED FLAT OLED
// =========================================================================

/* [Render Selection] */
// Export "base", "lid", "knob", and "clamps" (or "all" to preview/print together)
render_mode = "clamps"; // ["all", "base", "lid", "knob", "clamps"]

/* [2.5" HDD Screw (M3) Settings] */
// Standard 2.5" HDD/SSD screws: M3 thread (3.0mm), ~5.4-5.8mm flat wafer head
m3_pilot_dia = 2.75;  // Self-threading pilot hole for M3 screws
m3_clear_dia = 3.4;   // Through-hole clearance for M3 screw in clamp bars
pcb_thick    = 1.60;  // Standard fiberglass PCB thickness
clamp_wall_h = 1.25;  // CRITICAL: Towers stop 0.35mm BELOW the top of the 1.6mm PCB
                      // so flat M3 screw heads & clamp bars ALWAYS bite the PCB first!
m3_edge_off  = 2.0;   // Center of M3 hole is 2.0mm from PCB edge -> 5.5mm screw head overlaps PCB by 0.75mm!

/* [Enclosure Dimensions] */
box_length  = 124;    // X-axis width (mm) - fits freestanding Pico posts + flat 61mm LiPo side-by-side
box_width   = 56;     // Y-axis depth (mm)
base_height = 28;     // Interior height for Pico & DuPont wires
lid_height  = 12;     // Top faceplate skirt height (mm)
wall_thick  = 2.4;    // 3 perimeters with a 0.4mm nozzle
corner_rad  = 4.0;

/* [1. Raspberry Pi Pico W Official Dimensions] */
pico_pcb_l  = 51.2;   // 51.0mm PCB + 0.2mm clearance
pico_pcb_w  = 21.2;   // 21.0mm PCB + 0.2mm clearance
pico_hole_x = 47.0;   // Exact center-to-center X hole spacing
pico_hole_y = 11.4;   // Exact center-to-center Y hole spacing

/* [2. Adafruit 2500mAh LiPo & #2124 Backpack Dimensions] */
lipo_length = 62.5;   // Fits 61mm battery + clearance
lipo_width  = 48.2;   // Fits 47mm battery + clearance
lipo_thick  = 7.5;

// Adafruit LiIon/LiPoly Backpack (#2124) mounted HORIZONTALLY along back wall:
bp_horiz_x  = 17.4;   // 17.0mm board length + 0.4mm clearance (X-axis)
bp_horiz_y  = 15.4;   // 15.0mm board width + 0.4mm clearance (Y-axis)
backpack_pin_depth = 6.0; // Deep open pit underneath for protruding solder pins

/* [3. 0.96" SSD1306 OLED Dimensions (Flat Against Ceiling, 2x Side Screws Only)] */
oled_window_w   = 26.0;
oled_window_h   = 14.5;
oled_pcb_w      = 27.6;
oled_pcb_h      = 27.8;

/* [4. Keyestudio KS0013 / KY-040 Rotary Encoder Dimensions] */
ks0013_shaft_dia       = 7.3;
ks0013_pcb_l           = 26.8;
ks0013_pcb_w           = 19.3;
ks0013_shaft_from_back = 10.5;
ks0013_standoff_h      = 6.2;

/* [5. Low-Profile Knurled D-Shaft Knob (24x14mm)] */
knob_outer_dia  = 24.0;
knob_height     = 14.0;
knob_skirt_h    = 3.0;
knob_skirt_dia  = 20.0;
shaft_dia       = 6.15;
shaft_flat_thk  = 4.65;
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
    translate([box_length + 12, 5, 0])
        clamp_bars_set();
} else if (render_mode == "base") {
    bottom_base();
} else if (render_mode == "lid") {
    translate([0, 0, lid_height])
        rotate([180, 0, 0])
            top_lid();
} else if (render_mode == "knob") {
    encoder_knob();
} else if (render_mode == "clamps") {
    clamp_bars_set();
}

// =========================================================================
// 1. BOTTOM BASE (Freestanding Pico Posts & Horizontal Back-Wall Backpack)
// =========================================================================
module bottom_base() {
    pico_center_x = wall_thick + 1.5 + (pico_pcb_l / 2); // X = 29.5mm
    pico_center_y = 16.5;                                // Pico spans Y = 5.9mm to 27.1mm
    pico_deck_z   = wall_thick + 6.5;                    // Z = 8.9mm (6.5mm pin clearance underneath)

    // LiPo battery tray sits on the right side of the floor, clear of the freestanding Pico posts
    lipo_x = box_length - wall_thick - lipo_length - 1.0; // X = 58.1mm to 120.6mm
    lipo_y = (box_width - lipo_width) / 2;                // Y = 3.9mm to 52.1mm

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

        // Micro-USB cutout on left wall (aligned with Pico center Y=16.5, Z=8.9mm)
        translate([-0.5, pico_center_y - 5.5, pico_deck_z - 1.0])
            cube([wall_thick + 2, 11, 7.5]);
        translate([-0.5, pico_center_y - 7.5, pico_deck_z - 2.5])
            cube([1.4, 15, 10.5]);

        // Front & Back Internal Snap-Catch Grooves for Case Lid
        for (x_pos = [28, box_length - 28]) {
            translate([x_pos - 7, wall_thick - 0.9, base_height - 4.2])
                cube([14, 1.2, 2.4]);
            translate([x_pos - 7, box_width - wall_thick - 0.3, base_height - 4.2])
                cube([14, 1.2, 2.4]);
        }

        // Pry notch on right seam
        translate([box_length - 1.2, box_width/2 - 6, base_height - 1.2])
            cube([2.0, 12, 1.5]);
    }

    // --- A. FLOOR TRAY FOR ADAFRUIT 3.7V 2500mAh LIPO ---
    translate([lipo_x + lipo_length, lipo_y, wall_thick]) {
        cube([1.6, lipo_width, lipo_thick]);
        translate([-0.8, lipo_width/2 - 10, lipo_thick - 0.4])
            cube([2.4, 20, 1.2]);
    }
    translate([lipo_x - 1.6, lipo_y + 24.0, wall_thick])
        cube([1.6, lipo_width - 24.0, lipo_thick]);

    // --- B. FREESTANDING RASPBERRY PI PICO W POSTS (Zero Bars Underneath!) ---
    for (sx = [-1, 1]) {
        for (sy = [-1, 1]) {
            hx = pico_center_x + sx * (pico_hole_x / 2);
            hy = pico_center_y + sy * (pico_hole_y / 2);
            translate([hx, hy, wall_thick]) {
                cylinder(d=5.2, h=pico_deck_z - wall_thick - 3.5);
                cylinder(d=3.6, h=pico_deck_z - wall_thick);
                translate([0, 0, pico_deck_z - wall_thick])
                    cylinder(d1=1.65, d2=1.1, h=1.8);
            }
        }
    }

    // 2. Two Freestanding Sub-Flush M3 Edge-Clamp Towers at Right End of Pico W
    pico_post_x  = pico_center_x + pico_pcb_l/2 + m3_edge_off;
    pico_tower_h = (pico_deck_z - wall_thick) + clamp_wall_h;
    difference() {
        union() {
            for (sy = [-1, 1]) {
                translate([pico_post_x, pico_center_y + sy * 4.5, wall_thick])
                    cylinder(d=6.2, h=pico_tower_h);
            }
        }
        for (sy = [-1, 1]) {
            translate([pico_post_x, pico_center_y + sy * 4.5, wall_thick + pico_tower_h - 8.0])
                cylinder(d=m3_pilot_dia, h=9.0);
        }
        translate([pico_center_x - pico_pcb_l/2, pico_center_y - pico_pcb_w/2, pico_deck_z])
            cube([pico_pcb_l, pico_pcb_w, 10.0]);
    }

    // --- C. HORIZONTAL BACK-WALL BACKPACK CRADLE (Sub-Flush M3 Towers) ---
    bp_x      = 16.0;
    bp_y      = box_width - wall_thick - bp_horiz_y - 1.2;
    bp_seat_z = 6.5;
    bp_wall_h = bp_seat_z + clamp_wall_h;

    translate([bp_x, bp_y, wall_thick]) {
        difference() {
            union() {
                translate([-1.6, -1.6, 0])
                    cube([bp_horiz_x + 3.2, bp_horiz_y + 2.8, bp_wall_h]);

                translate([-m3_edge_off, bp_horiz_y / 2, 0])
                    cylinder(d=6.4, h=bp_wall_h);
                translate([bp_horiz_x + m3_edge_off, bp_horiz_y / 2, 0])
                    cylinder(d=6.4, h=bp_wall_h);
            }

            translate([-m3_edge_off, bp_horiz_y / 2, bp_wall_h - 7.0])
                cylinder(d=m3_pilot_dia, h=8.0);
            translate([bp_horiz_x + m3_edge_off, bp_horiz_y / 2, bp_wall_h - 7.0])
                cylinder(d=m3_pilot_dia, h=8.0);

            translate([0, 0, bp_seat_z])
                cube([bp_horiz_x, bp_horiz_y, 10.0]);

            translate([1.3, 1.3, bp_seat_z - backpack_pin_depth])
                cube([bp_horiz_x - 2.6, bp_horiz_y - 2.6, backpack_pin_depth + 0.5]);

            translate([1.3, -2.0, bp_seat_z - backpack_pin_depth])
                cube([bp_horiz_x - 2.6, 3.8, backpack_pin_depth + 10.0]);

            translate([bp_horiz_x - 1.5, 0.8, bp_seat_z - 1.0])
                cube([5.0, 5.5, 10.0]);
        }
    }
}

// =========================================================================
// 2. TOP LID (Sub-Flush M3 Towers for KS0013 Encoder & Deep-Tapped OLED)
// =========================================================================
module top_lid() {
    oled_cx = 38;
    oled_cy = box_width / 2;
    oled_side_off = oled_pcb_w/2 + m3_edge_off;

    enc_cx  = 88;
    enc_cy  = box_width / 2;

    ceiling_z = lid_height - wall_thick;

    difference() {
        union() {
            rounded_box(box_length, box_width, lid_height, corner_rad);

            lip_clearance = 0.3;
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

        // 2. KS0013 Rotary Encoder Shaft Hole
        translate([enc_cx, enc_cy, ceiling_z - 0.5])
            cylinder(d=ks0013_shaft_dia, h=wall_thick + 1);

        // 3. DEEP OLED PILOT HOLES INTO THE LID CEILING (1.8mm deep into the 2.4mm roof!)
        // Gives 3.05mm total screw depth while keeping the towers only 1.25mm tall!
        for (side = [-1, 1]) {
            translate([oled_cx + side * oled_side_off, oled_cy, ceiling_z - 0.1])
                cylinder(d=m3_pilot_dia, h=wall_thick - 0.5);
        }
    }

    // --- A. 4x Cantilever Case Snap-Fit Tabs (Front & Back Edges) ---
    for (x_pos = [28, box_length - 28]) {
        translate([x_pos - 5, wall_thick + 0.3, -4.2]) {
            cube([10, 1.4, 5.0]);
            translate([0, -0.55, 0.4])
                cube([10, 1.95, 1.3]);
        }
        translate([x_pos - 5, box_width - wall_thick - 1.7, -4.2]) {
            cube([10, 1.4, 5.0]);
            translate([0, 0, 0.4])
                cube([10, 1.95, 1.3]);
        }
    }

    // --- B. KS0013 ENCODER POCKET + SUB-FLUSH M3 SCREW TOWERS ---
    pcb_min_x    = enc_cx - (ks0013_pcb_l - ks0013_shaft_from_back);
    rail_len     = 16.0;
    rail_x       = pcb_min_x + ks0013_pcb_l - rail_len;
    enc_wall_h   = ks0013_standoff_h + clamp_wall_h;
    enc_boss_off = ks0013_pcb_w/2 + m3_edge_off;

    difference() {
        union() {
            for (dir = [-1, 1]) {
                ledge_y = (dir == -1) ? (enc_cy - ks0013_pcb_w/2) : (enc_cy + ks0013_pcb_w/2 - 2.0);
                translate([rail_x, ledge_y, ceiling_z - ks0013_standoff_h])
                    cube([rail_len, 2.0, ks0013_standoff_h]);

                wall_y = (dir == -1) ? (enc_cy - ks0013_pcb_w/2 - 1.5) : (enc_cy + ks0013_pcb_w/2);
                translate([rail_x, wall_y, ceiling_z - enc_wall_h])
                    cube([rail_len, 1.5, enc_wall_h]);

                translate([enc_cx + 1.0, enc_cy + dir * enc_boss_off, ceiling_z - enc_wall_h])
                    cylinder(d=6.5, h=enc_wall_h);
            }
            translate([pcb_min_x + ks0013_pcb_l, enc_cy - ks0013_pcb_w/2, ceiling_z - enc_wall_h])
                cube([1.6, ks0013_pcb_w, enc_wall_h]);
        }

        for (dir = [-1, 1]) {
            translate([enc_cx + 1.0, enc_cy + dir * enc_boss_off, ceiling_z - enc_wall_h - 0.5])
                cylinder(d=m3_pilot_dia, h=enc_wall_h - 0.4);
        }

        translate([pcb_min_x, enc_cy - ks0013_pcb_w/2, ceiling_z - ks0013_standoff_h - 10.0])
            cube([ks0013_pcb_l, ks0013_pcb_w, 10.0]);
    }

    // --- C. SSD1306 OLED: FLAT AGAINST LID CEILING + 2x SIDE M3 CLAMP TOWERS ONLY ---
    difference() {
        union() {
            for (side = [-1, 1]) {
                translate([oled_cx + side * oled_side_off, oled_cy, ceiling_z - clamp_wall_h])
                    cylinder(d=6.8, h=clamp_wall_h);
            }
        }

        // Drill all the way through the 1.25mm tower into the ceiling pocket above
        for (side = [-1, 1]) {
            translate([oled_cx + side * oled_side_off, oled_cy, ceiling_z - clamp_wall_h - 0.5])
                cylinder(d=m3_pilot_dia, h=clamp_wall_h + 1.0);
        }

        translate([oled_cx - oled_pcb_w/2, oled_cy - oled_pcb_h/2, ceiling_z - 10.0])
            cube([oled_pcb_w, oled_pcb_h, 10.0]);
    }
}

// =========================================================================
// 3. STEPPED M3 CLAMP BARS (Includes Full-Width Recessed OLED Bridge Clamp!)
// =========================================================================
module clamp_bars_set() {
    // 1. Encoder Bridge Clamp Bar
    enc_span = ks0013_pcb_w + 2 * m3_edge_off;
    difference() {
        union() {
            hull() {
                translate([0, -enc_span/2, 0]) cylinder(d=7.0, h=2.2);
                translate([0,  enc_span/2, 0]) cylinder(d=7.0, h=2.2);
            }
            translate([-3.5, -(ks0013_pcb_w - 1.0)/2, 2.2])
                cube([7.0, ks0013_pcb_w - 1.0, 0.5]);
        }
        translate([0, -enc_span/2, -0.1]) cylinder(d=m3_clear_dia, h=3.5);
        translate([0,  enc_span/2, -0.1]) cylinder(d=m3_clear_dia, h=3.5);
    }

    // 2. Pico End Clamp Bar
    translate([10, 0, 0]) {
        difference() {
            hull() {
                translate([0, -4.5, 0]) cylinder(d=6.8, h=2.2);
                translate([0,  4.5, 0]) cylinder(d=6.8, h=2.2);
            }
            translate([0, -4.5, -0.1]) cylinder(d=m3_clear_dia, h=3.0);
            translate([0,  4.5, -0.1]) cylinder(d=m3_clear_dia, h=3.0);
        }
    }

    // 3. Horizontal Backpack Bridge Clamp Bar
    bp_span = bp_horiz_x + 2 * m3_edge_off;
    translate([20, 0, 0]) {
        difference() {
            union() {
                hull() {
                    translate([0, -bp_span/2, 0]) cylinder(d=6.8, h=2.2);
                    translate([0,  bp_span/2, 0]) cylinder(d=6.8, h=2.2);
                }
                translate([-3.4, -(bp_horiz_x - 1.0)/2, 2.2])
                    cube([6.8, bp_horiz_x - 1.0, 0.5]);
            }
            translate([0, -bp_span/2, -0.1]) cylinder(d=m3_clear_dia, h=3.5);
            translate([0,  bp_span/2, -0.1]) cylinder(d=m3_clear_dia, h=3.5);
        }
    }

    // 4. NEW: SSD1306 OLED Full-Width Bridge Clamp Bar (Spans both side M3 towers!)
    // Features two 0.5mm edge pinch pads that press the outer 2.2mm left/right margins
    // of the OLED PCB, while arching over the SMD components in the center of the board!
    oled_span = oled_pcb_w + 2 * m3_edge_off; // 31.6mm center-to-center hole span
    translate([31, 0, 0]) {
        difference() {
            union() {
                // Main structural bridge bar (8mm wide for anti-rocking stability)
                hull() {
                    translate([0, -oled_span/2, 0]) cylinder(d=8.0, h=2.4);
                    translate([0,  oled_span/2, 0]) cylinder(d=8.0, h=2.4);
                }
                // Left & Right 0.5mm stepped pinch pads (contacts only the outer 2.2mm PCB edges)
                for (side = [-1, 1]) {
                    pad_y = (side == -1) ? (-oled_pcb_w/2 + 0.2) : (oled_pcb_w/2 - 2.4);
                    translate([-4.0, pad_y, 2.4])
                        cube([8.0, 2.2, 0.5]);
                }
            }
            // M3 screw clearance holes
            translate([0, -oled_span/2, -0.1]) cylinder(d=m3_clear_dia, h=3.5);
            translate([0,  oled_span/2, -0.1]) cylinder(d=m3_clear_dia, h=3.5);

            // Center SMD component relief channel (clears resistors/caps on back of OLED PCB)
            translate([-4.5, -(oled_pcb_w - 5.2)/2, 1.8])
                cube([9.0, oled_pcb_w - 5.2, 2.0]);
        }
    }
}

// =========================================================================
// 4. KNURLED D-SHAFT KNOB (24 x 14mm Low-Profile)
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

        translate([0, 0, -0.1]) {
            intersection() {
                cylinder(d=shaft_dia, h=shaft_depth + 0.1);
                translate([-shaft_dia/2, -shaft_dia + shaft_flat_thk, 0])
                    cube([shaft_dia, shaft_dia, shaft_depth + 0.2]);
            }
        }

        translate([0, knob_outer_dia/2 - 4.5, knob_height - 1.2])
            cylinder(d=2.4, h=2.0);
    }
}

// =========================================================================
// HELPER MODULES
// =========================================================================
module rounded_box(l, w, h, r) {
    hull() {
        translate([r, r, 0])         cylinder(r=r, h=h);
        translate([l - r, r, 0])     cylinder(r=r, h=h);
        translate([r, w - r, 0])     cylinder(r=r, h=h);
        translate([l - r, w - r, 0]) cylinder(r=r, h=h);
    }
}