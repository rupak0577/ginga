#
# Mosaic.py -- Mosaic plugin for Ginga FITS viewer
# 
# Eric Jeschke (eric@naoj.org)
#
# Copyright (c)  Eric R. Jeschke.  All rights reserved.
# This is open-source software licensed under a BSD license.
# Please see the file LICENSE.txt for details.
#
import math
import time
import numpy
import os.path
import threading

from ginga import AstroImage
from ginga.util import wcs, mosaic, iqcalc
from ginga import GingaPlugin
from ginga.misc import Widgets, CanvasTypes

class Mosaic(GingaPlugin.LocalPlugin):

    def __init__(self, fv, fitsimage):
        # superclass defines some variables for us, like logger
        super(Mosaic, self).__init__(fv, fitsimage)

        self.count = 0
        self.img_mosaic = None
        self.bg_ref = 0.0
        self.ev_intr = threading.Event()
        
        self.dc = self.fv.getDrawClasses()

        canvas = self.dc.DrawingCanvas()
        canvas.enable_draw(False)
        canvas.add_callback('drag-drop', self.drop_cb)
        canvas.setSurface(fitsimage)
        self.canvas = canvas
        self.layertag = 'mosaic-canvas'

        # Set preferences for destination channel
        prefs = self.fv.get_preferences()
        self.settings = prefs.createCategory('plugin_Mosaic')
        self.settings.setDefaults(annotate_images=True, fov_deg=1.0,
                                  match_bg=False, trim_px=0)
        self.settings.load(onError='silent')


    def build_gui(self, container):
        sw = Widgets.ScrollArea()

        vbox1 = Widgets.VBox()
        vbox1.set_border_width(4)
        vbox1.set_spacing(2)

        self.msgFont = self.fv.getFont("sansFont", 12)
        tw = Widgets.TextArea(wrap=True, editable=False)
        tw.set_font(self.msgFont)
        self.tw = tw

        fr = Widgets.Frame("Instructions")
        fr.set_widget(tw)
        vbox1.add_widget(fr, stretch=0)
        
        fr = Widgets.Frame("Mosaic")

        captions = [
            ("FOV (deg):", 'label', 'Fov', 'llabel'),
            ("Set FOV:", 'label', 'Set FOV', 'entry'),
            ("New Mosaic", 'button'),
            ("Label images", 'checkbutton', "Match bg", 'checkbutton'),
            ("Trim Pixels:", 'label', 'Trim Px', 'llabel'),
            ("Set Trim Pixels:", 'label', 'Trim Pixels', 'entry'),
            ("Merge data", 'checkbutton'),
            ]
        w, b = Widgets.build_info(captions)
        self.w = b

        fov_deg = self.settings.get('fov_deg', 1.0)
        b.fov.set_text(str(fov_deg))
        b.set_fov.set_length(8)
        b.set_fov.set_text(str(fov_deg))
        b.set_fov.add_callback('activated', self.set_fov_cb)
        b.set_fov.set_tooltip("Set size of mosaic FOV (deg)")
        b.new_mosaic.add_callback('activated', lambda w: self.new_mosaic_cb())
        labelem = self.settings.get('annotate_images', False)
        b.label_images.set_state(labelem)
        b.label_images.set_tooltip("Label tiles with their names")
        b.label_images.add_callback('activated', self.annotate_cb)

        trim_px = self.settings.get('trim_px', 0)
        match_bg = self.settings.get('match_bg', False)
        b.match_bg.set_tooltip("Try to match background levels")
        b.match_bg.set_state(match_bg)
        b.match_bg.add_callback('activated', self.match_bg_cb)
        b.trim_pixels.set_tooltip("Set number of pixels to trim from each edge")
        b.trim_px.set_text(str(trim_px))
        b.trim_pixels.add_callback('activated', self.trim_pixels_cb)
        b.trim_pixels.set_length(8)

        merge = self.settings.get('merge', False)
        b.merge_data.set_tooltip("Merge data instead of overlay")
        b.merge_data.set_state(merge)
        b.merge_data.add_callback('activated', self.merge_cb)

        fr.set_widget(w)
        vbox1.add_widget(fr, stretch=0)

        # Mosaic evaluation status
        hbox = Widgets.HBox()
        hbox.set_spacing(4)
        hbox.set_border_width(4)
        label = Widgets.Label()
        self.w.eval_status = label
        hbox.add_widget(self.w.eval_status, stretch=0)
        hbox.add_widget(Widgets.Label(''), stretch=1)                
        vbox1.add_widget(hbox, stretch=0)

        # Mosaic evaluation progress bar and stop button
        hbox = Widgets.HBox()
        hbox.set_spacing(4)
        hbox.set_border_width(4)
        btn = Widgets.Button("Stop")
        btn.add_callback('activated', lambda w: self.eval_intr())
        btn.set_enabled(False)
        self.w.btn_intr_eval = btn
        hbox.add_widget(btn, stretch=0)

        self.w.eval_pgs = Widgets.ProgressBar()
        hbox.add_widget(self.w.eval_pgs, stretch=1)
        vbox1.add_widget(hbox, stretch=0)
        
        spacer = Widgets.Label('')
        vbox1.add_widget(spacer, stretch=1)
        
        btns = Widgets.HBox()
        btns.set_spacing(3)

        btn = Widgets.Button("Close")
        btn.add_callback('activated', lambda w: self.close())
        btns.add_widget(btn, stretch=0)
        btns.add_widget(Widgets.Label(''), stretch=1)
        vbox1.add_widget(btns, stretch=0)

        sw.set_widget(vbox1)
        container.add_widget(sw, stretch=1)


    def prepare_mosaic(self, image, fov_deg):
        """Prepare a new (blank) mosaic image based on the pointing of
        the parameter image
        """
        header = image.get_header()
        ra_deg, dec_deg = header['CRVAL1'], header['CRVAL2']

        data_np = image.get_data()
        self.bg_ref = iqcalc.get_mean(data_np)
            
        # TODO: handle skew (differing rotation for each axis)?
        (rot_deg, cdelt1, cdelt2) = wcs.get_rotation_and_scale(header)
        self.logger.debug("image0 rot=%f cdelt1=%f cdelt2=%f" % (
            rot_deg, cdelt1, cdelt2))

        # TODO: handle differing pixel scale for each axis?
        px_scale = math.fabs(cdelt1)
        #cdbase = [numpy.sign(cdelt1), numpy.sign(cdelt2)]
        cdbase = [1, 1]

        self.logger.debug("creating blank image to hold mosaic")
        self.fv.gui_do(self._prepare_mosaic1)

        img_mosaic = mosaic.create_blank_image(ra_deg, dec_deg,
                                               fov_deg, px_scale,
                                               rot_deg, 
                                               cdbase=cdbase,
                                               logger=self.logger)

        imname = 'mosaic%d' % (self.count)
        img_mosaic.set(name=imname)
        self.count += 1

        header = img_mosaic.get_header()
        (rot, cdelt1, cdelt2) = wcs.get_rotation_and_scale(header)
        self.logger.debug("mosaic rot=%f cdelt1=%f cdelt2=%f" % (
            rot, cdelt1, cdelt2))

        self.img_mosaic = img_mosaic
        chname = self.fv.get_channelName(self.fitsimage)
        self.fv.gui_call(self.fv.add_image, imname, img_mosaic,
                         chname=chname)
        
    def _prepare_mosaic1(self):
        self.canvas.deleteAllObjects()
        self.update_status("Creating blank image...")

    def ingest_one(self, image):
        imname = image.get('name', 'image')
        imname, ext = os.path.splitext(imname)

        # Get optional parameters
        trim_px = self.settings.get('trim_px', 0)
        match_bg = self.settings.get('match_bg', False)
        merge = self.settings.get('merge', False)
        bg_ref = None
        if match_bg:
            bg_ref = self.bg_ref

        msg = "Processing '%s' ..." % (imname)
        self.update_status(msg)
        self.logger.info(msg)
        loc = self.img_mosaic.mosaic_inline([ image ],
                                            bg_ref=bg_ref,
                                            trim_px=trim_px,
                                            merge=merge)

        (xlo, ylo, xhi, yhi) = loc

        # annotate ingested image with its name?
        if self.settings.get('annotate_images', False):
            x, y = (xlo+xhi)//2, (ylo+yhi)//2
            self.canvas.add(self.dc.Text(x, y, imname, color='red'))
        

    def close(self):
        self.img_mosaic = None
        chname = self.fv.get_channelName(self.fitsimage)
        self.fv.stop_local_plugin(chname, str(self))
        return True
        
    def instructions(self):
        self.tw.set_text("""Set the FOV and drag files onto the window.""")
            
    def start(self):
        self.instructions()
        # insert layer if it is not already
        try:
            obj = self.fitsimage.getObjectByTag(self.layertag)

        except KeyError:
            # Add canvas layer
            self.fitsimage.add(self.canvas, tag=self.layertag)

        self.resume()

    def stop(self):
        self.canvas.ui_setActive(False)
        try:
            self.fitsimage.deleteObjectByTag(self.layertag)
        except:
            pass
        self.fv.showStatus("")

    def pause(self):
        self.canvas.ui_setActive(False)
        
    def resume(self):
        self.canvas.ui_setActive(True)

    def new_mosaic_cb(self):
        self.img_mosaic = None
        self.fitsimage.onscreen_message("Drag new files...",
                                        delay=2.0)
        
    def drop_cb(self, canvas, paths):
        self.logger.info("files dropped: %s" % str(paths))
        self.fv.nongui_do(self.fv.error_wrap, self.mosaic, paths)
        return True
        
    def annotate_cb(self, widget, tf):
        self.settings.set(annotate_images=tf)

    def mosaic(self, paths):
        # NOTE: this runs in a non-gui thread

        # Initialize progress bar
        total_files = len(paths)
        count = 1
        self.ev_intr.clear()
        self.read_elapsed = 0.0
        self.process_elapsed = 0.0
        self.fv.gui_do(self.init_progress)
        self.start_time = time.time()

        first = paths[0]
        image = self.fv.load_image(first)

        time_intr1 = time.time()
        self.read_elapsed += time_intr1 - self.start_time
        
        fov_deg = self.settings.get('fov_deg', 1.0)

        # If there is no current mosaic then prepare a new one
        if self.img_mosaic == None:
            self.prepare_mosaic(image, fov_deg)
        else:
            # get our center position
            ctr_x, ctr_y = self.img_mosaic.get_center()
            ra1_deg, dec1_deg = self.img_mosaic.pixtoradec(ctr_x, ctr_y)

            # get new image's center position
            ctr_x, ctr_y = image.get_center()
            ra2_deg, dec2_deg = image.pixtoradec(ctr_x, ctr_y)

            # distance between our center and new image's center
            dist = image.deltaStarsRaDecDeg(ra1_deg, dec1_deg,
                                            ra2_deg, dec2_deg)
            # if distance is greater than current fov, start a new mosaic
            if dist > fov_deg:
                self.prepare_mosaic(image, fov_deg)

        self.fv.gui_call(self.fv.error_wrap, self.ingest_one, image)
        self.update_progress(float(count)/total_files)

        time_intr2 = time.time()
        self.process_elapsed += time_intr2 - time_intr1

        for url in paths[1:]:
            if self.ev_intr.isSet():
                break
            time_intr1 = time.time()
            image = self.fv.load_image(url)

            time_intr2 = time.time()
            self.read_elapsed += time_intr2 - time_intr1

            self.fv.gui_call(self.fv.error_wrap, self.ingest_one, image)
            count += 1
            self.update_progress(float(count)/total_files)

            time_intr1 = time.time()
            self.process_elapsed += time_intr1 - time_intr2

        self.end_progress()
        self.update_status("Done. Read=%.2f Process=%.2f (sec)" % (
            self.read_elapsed, self.process_elapsed))

    def set_fov_cb(self, w):
        fov_deg = float(w.get_text())
        self.settings.set(fov_deg=fov_deg)
        self.w.fov.set_text(str(fov_deg))
        
    def trim_pixels_cb(self, w):
        trim_px = int(w.get_text())
        self.w.trim_px.set_text(str(trim_px))
        self.settings.set(trim_px=trim_px)
        
    def match_bg_cb(self, w, tf):
        self.settings.set(match_bg=tf)
        
    def merge_cb(self, w, tf):
        self.settings.set(merge=tf)
        
    def update_status(self, text):
        self.fv.gui_do(self.w.eval_status.set_text, text)

    def init_progress(self):
        self.w.btn_intr_eval.set_enabled(True)
        self.w.eval_pgs.set_value(0.0)
            
    def update_progress(self, pct):
        self.fv.gui_do(self.w.eval_pgs.set_value, pct)
        
    def end_progress(self):
        self.fv.gui_do(self.w.btn_intr_eval.set_enabled, False)

    def eval_intr(self):
        self.ev_intr.set()
        
    def __str__(self):
        return 'mosaic'
    
#END