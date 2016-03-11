#
# LineProfile.py -- LineProfile plugin for Ginga reference viewer
#
# This is open-source software licensed under a BSD license.
# Please see the file LICENSE.txt for details.
#
from ginga import GingaPlugin
from ginga.misc import Widgets, Plot, ParamSet, Bunch
from ginga.util import plots, aperture

import numpy as np


class LineProfile(GingaPlugin.LocalPlugin):

    def __init__(self, fv, fitsimage):
        super(LineProfile, self).__init__(fv, fitsimage)

        self.image = None
        self.layertag = 'lineprofile-canvas'
        self.raster_file = False
        self.pan2mark = False
        self.wd = None
        self.ht = None
        self.selected_axis = None
        self.hbox_axes = None

        self.dc = self.fv.getDrawClasses()
        canvas = self.dc.DrawingCanvas()
        canvas.set_callback('cursor-down', self.btndown_cb)
        canvas.set_callback('cursor-up', self.update)
        canvas.setSurface(self.fitsimage)
        canvas.register_for_cursor_drawing(self.fitsimage)
        self.canvas = canvas

        # For "marks" feature
        self.mark_radius = 10
        self.mark_style = 'cross'
        self.mark_color = 'purple'
        self.select_color = 'cyan'
        self.marks = ['None']
        self.mark_index = 0
        self.mark_selected = None
        self.tw = None
        self.mark_data_x = [None]
        self.mark_data_y = [None]

        # Aperture
        self.draw_enabled = False
        self.ap_draw_types = ['box','circle']
        self.ap_algo_types = ['mean','median','mode','stddev']
        self.draw_tags = []

        # cache of all canvas item parameters
        self.drawparams_cache = {}
        # holds object being edited
        self.edit_obj = None

        self.gui_up = False

    def build_gui(self, container):
        top = Widgets.VBox()
        top.set_border_width(4)

        vbox, sw, orientation = Widgets.get_oriented_box(container)
        vbox.set_margins(4, 4, 4, 4)
        vbox.set_spacing(2)

        self.msgFont = self.fv.getFont("sansFont", 12)
        tw = Widgets.TextArea(wrap=True, editable=False)
        tw.set_font(self.msgFont)
        self.tw = tw

        fr = Widgets.Expander("Instructions")
        vbox2 = Widgets.VBox()
        vbox2.add_widget(tw)
        vbox2.add_widget(Widgets.Label(''), stretch=1)
        fr.set_widget(vbox2)
        vbox.add_widget(fr, stretch=0)

        # Add Tab Widget
        nb = Widgets.TabWidget(tabpos='bottom')
        vbox.add_widget(nb, stretch=0)

        self.lp_plot = plots.Plot(logger=self.logger,
                               width=400, height=300)
        self.plot = Plot.PlotWidget(self.lp_plot)
        ax = self.lp_plot.add_axis()
        ax.grid(False)

        self.ap_plot = plots.Plot(logger=self.logger,
                                    width=400, height=400)
        self.ap_plot.add_axis()
        self.plot2 = Plot.PlotWidget(self.ap_plot)
        self.plot2.resize(400, 400)

        # Add Cuts plot to its tab
        vbox_lp = Widgets.VBox()
        vbox_lp.add_widget(self.plot, stretch=1)
        nb.add_widget(vbox_lp, title="Line Profile")

        # Add Cuts plot to its tab
        vbox_ap = Widgets.VBox()
        vbox_ap.add_widget(self.plot2, stretch=1)
        nb.add_widget(vbox_ap, title="Aperture")

        fr = Widgets.Frame("Axes controls")
        self.hbox_axes = Widgets.HBox()
        self.hbox_axes.set_border_width(4)
        self.hbox_axes.set_spacing(1)
        fr.set_widget(self.hbox_axes)

        vbox.add_widget(fr, stretch=0)

        btns = Widgets.HBox()
        btns.set_border_width(4)
        btns.set_spacing(4)

        # control for selecting a mark
        cbox2 = Widgets.ComboBox()
        for tag in self.marks:
            cbox2.append_text(tag)
        if self.mark_selected is None:
            cbox2.set_index(0)
        else:
            cbox2.show_text(self.mark_selected)
        cbox2.add_callback('activated', self.mark_select_cb)
        self.w.marks = cbox2
        cbox2.set_tooltip("Select a mark")
        btns.add_widget(cbox2, stretch=0)

        btn1 = Widgets.CheckBox("Pan to mark")
        btn1.set_state(self.pan2mark)
        btn1.add_callback('activated', self.pan2mark_cb)
        btn1.set_tooltip("Pan follows selected mark")
        btns.add_widget(btn1)
        btns.add_widget(Widgets.Label(''), stretch=1)

        btn2 = Widgets.Button("Delete")
        self.del_btn = btn2
        btn2.add_callback('activated', lambda w: self.clear_mark_cb())
        btn2.set_tooltip("Delete selected mark")
        btn2.set_enabled(False)
        btns.add_widget(btn2, stretch=0)

        btn3 = Widgets.Button("Delete All")
        self.del_all_btn = btn3
        btn3.add_callback('activated', lambda w: self.clear_all())
        btn3.set_tooltip("Clear all marks")
        btn3.set_enabled(False)
        btns.add_widget(btn3, stretch=0)

        vbox2 = Widgets.VBox()
        vbox2.add_widget(btns, stretch=0)
        vbox2.add_widget(Widgets.Label(''), stretch=1)

        fr = Widgets.Frame("Mark controls")
        fr.set_widget(vbox2)
        vbox.add_widget(fr, stretch=1)

        # Aperture controls
        captions = (('Draw Type:', 'label', 'Draw Type', 'combobox',
                     'Algorithm:', 'label', 'Algorithm', 'combobox'),
                    ("Sigma:", 'label', "Sigma", 'entry',
                     "Number of Iterations:", 'label', "Iterations", 'entry'),)
        w, b = Widgets.build_info(captions, orientation=orientation)
        self.w.update(b)

        # Set default sigma and iterations
        self.w.sigma.set_text(str(1.8))
        self.w.iterations.set_text(str(10))

        # control for selecting aperture type
        combobox = b.draw_type
        for type in self.ap_draw_types:
            combobox.append_text(type)
        combobox.set_index(0)
        combobox.add_callback('activated', lambda w, idx: self.set_drawparams_cb())

        # control for selecting algorithm
        combobox = b.algorithm
        for algo in self.ap_algo_types:
            combobox.append_text(algo)
        combobox.set_index(0)

        btn = Widgets.CheckBox("Enable Drawing")
        btn.set_state(self.draw_enabled)
        btn.add_callback('activated', self.draw_enabled_cb)

        mode = self.canvas.get_draw_mode()

        hbox = Widgets.HBox()
        btn1 = Widgets.RadioButton("Draw")
        btn1.set_state(mode == 'draw')
        btn1.add_callback('activated', lambda w, val: self.set_mode_cb('draw', val))
        btn1.set_tooltip("Choose this to draw")
        self.w.btn_draw = btn1
        self.w.btn_draw.set_enabled(False)
        hbox.add_widget(btn1)

        btn2 = Widgets.RadioButton("Edit", group=btn1)
        btn2.set_state(mode == 'edit')
        btn2.add_callback('activated', lambda w, val: self.set_mode_cb('edit', val))
        btn2.set_tooltip("Choose this to edit")
        self.w.btn_edit = btn2
        self.w.btn_edit.set_enabled(False)
        hbox.add_widget(btn2)

        btn2 = Widgets.Button("Clear canvas")
        btn2.add_callback('activated', lambda w: self.clear_canvas())
        btn2.set_tooltip("Delete all draw objects")

        hbox.add_widget(btn)
        hbox.add_widget(btn2)
        hbox.add_widget(Widgets.Label(''), stretch=1)

        vbox2 = Widgets.VBox()
        vbox2.add_widget(w, stretch=0)
        vbox2.add_widget(hbox, stretch=0)
        vbox2.add_widget(Widgets.Label(''), stretch=1)

        fr = Widgets.Frame("Aperture")
        fr.set_widget(vbox2)
        vbox.add_widget(fr, stretch=1)

        # scroll bars will allow lots of content to be accessed
        top.add_widget(sw, stretch=1)

        # A button box that is always visible at the bottom
        btns = Widgets.HBox()
        btns.set_spacing(3)

        # Add a close button for the convenience of the user
        btn = Widgets.Button("Close")
        btn.add_callback('activated', lambda w: self.close())
        btns.add_widget(btn, stretch=0)
        btns.add_widget(Widgets.Label(''), stretch=1)
        top.add_widget(btns, stretch=0)

        # Add our GUI to the container
        container.add_widget(top, stretch=1)
        self.gui_up = True

        self.build_axes()

    def build_axes(self):
        if (not self.gui_up) or (self.hbox_axes is None):
            return
        self.hbox_axes.remove_all()
        self.selected_axis = None
        self.clear_plot()

        image = self.fitsimage.get_image()
        if image is not None:
            # Add Checkbox widgets
            # `image.naxispath` returns only mdim axes
            for i in range(1, len(image.naxispath)+3):
                chkbox = Widgets.CheckBox('NAXIS%d' % i)
                self.hbox_axes.add_widget(chkbox)

                # Disable axes for 2D images
                if len(image.naxispath) <= 0:
                    chkbox.set_enabled(False)
                else:
                    # Add callback
                    self.axes_callback_handler(chkbox, i)

    def axes_callback_handler(self, chkbox, pos):
        chkbox.add_callback('activated',
                            lambda w, tf: self.axis_toggle_cb(w, tf, pos))

    def axis_toggle_cb(self, w, tf, pos):
        children = self.hbox_axes.get_children()

        # Deactivate previously selected axis
        if self.selected_axis is not None:
            children[self.selected_axis-1].set_state(False)

        # Check if the old axis has been clicked
        if pos == self.selected_axis:
            self.selected_axis = None
            self.clear_plot()
        else:
            self.selected_axis = pos
            children[pos-1].set_state(tf)
            self.redraw_mark()

    def instructions(self):
        self.tw.set_text("""Select an axis and pick a point using the cursor. Left-click to mark position.
Use MultiDim to change step values of axes.""")

    def close(self):
        self.fv.stop_local_plugin(self.chname, str(self))
        self.gui_up = False
        return True

    def start(self):
        self.instructions()
        self.set_drawparams_cb()

        # insert layer if it is not already
        try:
            obj = self.fitsimage.getObjectByTag(self.layertag)

        except KeyError:
            # Add canvas layer
            self.fitsimage.add(self.canvas, tag=self.layertag)

        self.resume()

    def pause(self):
        self.canvas.ui_setActive(False)

    def resume(self):
        self.canvas.ui_setActive(True)
        self.redo()

    def stop(self):
        self.canvas.ui_setActive(False)
        try:
            self.fitsimage.deleteObjectByTag(self.layertag)
        except:
            pass

    def redo(self):
        # Get image being shown
        self.image = self.fitsimage.get_image()
        if self.image is None:
            return

        self.build_axes()

        self.wd, self.ht = self.image.get_size()

        self.redraw_mark()

    def _plot(self, mark=None):
        # Transpose array for easier slicing
        mddata = self.image.get_mddata().T
        naxes = mddata.ndim

        if self.selected_axis:
            axis_data = self.get_axis(self.selected_axis)
            slice_obj = self._slice(naxes, mk=mark)

            self.clear_plot()
            self.lp_plot.plot(axis_data, mddata[slice_obj])

    def _slice(self, naxes, mk):
        # Build N-dim slice
        slice_obj = [0] * naxes

        # For axes 1 and 2
        if mk is not None:
            slice_obj[0] = self.mark_data_x[mk]
            slice_obj[1] = self.mark_data_y[mk]

        # For axis > 3
        for i in range(2, naxes):
            slice_obj[i] = self.image.revnaxis[i-2] + 1

        # Slice selected axis
        slice_obj[self.selected_axis-1] = slice(None, None, None)

        return slice_obj

    def get_axis(self, i):
        try:
            header = self.image.get_header()
            axis = header.get('CRVAL%d' % i) + \
                   np.arange(0, header.get('NAXIS%d' % i), 1) * \
                   header.get('CDELT%d' % i)
            return axis
        except Exception as e:
            errmsg = "Error loading axis %d: %s" % (i, str(e))
            self.logger.error(errmsg)
            self.fv.error(errmsg)

    def clear_plot(self):
        self.lp_plot.clear()
        self.lp_plot.fig.canvas.draw()

    def draw_enabled_cb(self, w, val):
        self.draw_enabled = val

        if val == True:
            self.w.btn_draw.set_enabled(True)
            self.w.btn_edit.set_enabled(True)

            self.canvas.enable_draw(True)
            self.canvas.enable_edit(True)

            self.canvas.set_callback('draw-event', self.draw_cb)
            self.canvas.set_callback('edit-event', self.edit_cb)
            self.canvas.set_callback('edit-select', self.edit_select_cb)
        else:
            self.w.btn_draw.set_enabled(False)
            self.w.btn_edit.set_enabled(False)

            self.canvas.enable_draw(False)
            self.canvas.enable_edit(False)

            self.canvas.set_callback('cursor-down', self.btndown_cb)
            self.canvas.set_callback('cursor-up', self.update)

    def draw_cb(self, canvas, tag):
        obj = canvas.getObjectByTag(tag)
        self.draw_tags.append(tag)
        #self.plot_ap()
        self.logger.info("drew a %s" % (obj.kind))
        return True

    def edit_cb(self, fitsimage, obj):
        # <-- obj has been edited
        #self.logger.debug("edit event on canvas: obj=%s" % (obj))
        if obj != self.edit_obj:
            # edit object is new.  Update visual parameters
            self.edit_select_cb(fitsimage, obj)

    def set_mode_cb(self, mode, tf):
        if tf:
            self.canvas.set_draw_mode(mode)
            if mode == 'edit':
                self.edit_initialize(self.fitsimage, None)
            elif mode == 'draw':
                self.set_drawparams_cb()
        return True

    def set_drawparams_cb(self):
        if self.canvas.get_draw_mode() != 'draw':
            # if we are in edit mode then don't initialize draw
            return
        index = self.w.draw_type.get_index()
        kind = self.ap_draw_types[index]

        params = self.drawparams_cache.setdefault(kind, Bunch.Bunch())
        self.draw_params = ParamSet.ParamSet(self.logger, params)

        args, kwdargs = self.draw_params.get_params()
        self.canvas.set_drawtype(kind, **kwdargs)

    def edit_select_cb(self, fitsimage, obj):
        self.logger.debug("editing selection status has changed for %s" % str(obj))
        self.edit_initialize(fitsimage, obj)

    def edit_initialize(self, fitsimage, obj):
        self.edit_obj = obj
        if (obj is not None) and self.canvas.is_selected(obj):
            self.draw_params = ParamSet.ParamSet(self.logger, obj)
            self.draw_params.add_callback('changed', self.edit_params_changed_cb)

    def edit_params_changed_cb(self, paramObj, obj):
        obj.sync_state()
        # TODO: change whence to 0 if allowing editing of images
        whence = 2
        self.canvas.redraw(whence=whence)

    def plot_ap(self):
        sigma = float(self.w.sigma.get_text())
        niter = int(self.w.iterations.get_text())

        index = self.w.algorithm.get_index()
        algo = self.ap_algo_types[index]

        #data_masked = self.image.cutout_shape()
        #plot_data = aperture.calc_stat(data_masked,sigma,niter,algo)

    def clear_canvas(self):
        for tag in self.draw_tags:
            self.canvas.deleteObjectByTag(tag)
        self.draw_tags = []

    ### MARK FEATURE LOGIC ###

    def btndown_cb(self, canvas, event, data_x, data_y):
        if self.draw_enabled:
            # if we are in draw mode then don't update mark
            return
        # Disable plotting for 2D images
        image = self.fitsimage.get_image()
        if len(image.naxispath) <= 0:
            return

        # Exclude points outside boundaries
        if not 0 <= data_x < self.wd or not 0 <= data_y < self.ht:
            self.clear_plot()
            return

        if not self.mark_selected:
            self.mark_data_x.append(data_x)
            self.mark_data_y.append(data_y)
            self.add_mark(data_x, data_y)

            self.del_btn.set_enabled(True)
            self.del_all_btn.set_enabled(True)
        return True

    def update(self, canvas, event, data_x, data_y):
        if self.draw_enabled:
            # if we are in draw mode then don't update mark
            return
        tag = self.mark_selected
        if tag is None:
            return
        idx = int(tag.strip('mark'))
        obj = self.canvas.getObjectByTag(tag)
        obj.move_to(data_x+5, data_y)

        canvas.redraw(whence=3)

        # Exclude points outside boundaries
        if not 0 <= data_x < self.wd or not 0 <= data_y < self.ht:
            self.clear_plot()
            # Clear mark data
            self.mark_data_x[idx] = None
            self.mark_data_y[idx] = None
            return

        self.mark_data_x[idx] = data_x
        self.mark_data_y[idx] = data_y

        self.redraw_mark()
        return True

    def add_mark(self, data_x, data_y, radius=None, color=None, style=None):
        if not radius:
            radius = self.mark_radius
        if not color:
            color = self.mark_color
        if not style:
            style = self.mark_style

        self.logger.debug("Setting mark at %d,%d" % (data_x, data_y))
        self.mark_index += 1
        tag = 'mark%d' % (self.mark_index)
        tag = self.canvas.add(self.dc.CompoundObject(
            self.dc.Point(data_x, data_y, self.mark_radius,
                          style=style, color=color,
                          linestyle='solid'),
            self.dc.Text(data_x + 10, data_y, "%d" % (self.mark_index),
                         color=color)),
                              tag=tag)
        self.marks.append(tag)
        self.w.marks.append_text(tag)
        self.select_mark(tag, pan=False)

    def select_mark(self, tag, pan=True):
        # deselect the current selected mark, if there is one
        if self.mark_selected is not None:
            try:
                obj = self.canvas.getObjectByTag(self.mark_selected)
                obj.setAttrAll(color=self.mark_color)
            except:
                # old object may have been deleted
                pass

        self.mark_selected = tag
        if tag is None:
            self.w.marks.show_text('None')
            self.canvas.redraw(whence=3)
            return

        self.w.marks.show_text(tag)
        obj = self.canvas.getObjectByTag(tag)
        obj.setAttrAll(color=self.select_color)
        if self.pan2mark and pan:
            self.fitsimage.panset_xy(obj.objects[0].x, obj.objects[0].y)
        self.canvas.redraw(whence=3)

        self.redraw_mark()

    def redraw_mark(self):
        if self.mark_selected is None:
            return
        idx = int(self.mark_selected.strip('mark'))
        self._plot(mark=idx)

    def mark_select_cb(self, w, index):
        tag = self.marks[index]
        if index == 0:
            tag = None
            self.clear_plot()
            self.del_btn.set_enabled(False)
        else:
            self.del_btn.set_enabled(True)

        self.select_mark(tag)

    def pan2mark_cb(self, w, val):
        self.pan2mark = val

    def clear_mark_cb(self):
        tag = self.mark_selected
        if tag is None:
            return
        idx = int(tag.strip('mark'))
        self.canvas.deleteObjectByTag(tag)
        self.w.marks.delete_alpha(tag)
        self.marks.remove(tag)
        self.w.marks.set_index(0)
        self.mark_selected = None

        self.clear_plot()

        self.mark_data_x[idx] = None
        self.mark_data_y[idx] = None
        self.del_btn.set_enabled(False)
        if len(self.marks) == 1:
            self.del_all_btn.set_enabled(False)

    def clear_all(self):
        self.canvas.deleteAllObjects()
        for name in self.marks:
            self.w.marks.delete_alpha(name)
        self.marks = ['None']
        self.w.marks.append_text('None')
        self.w.marks.set_index(0)
        self.mark_index = 0
        self.mark_selected = None
        self.mark_data_x = [None]
        self.mark_data_y = [None]

        self.clear_plot()

        self.del_btn.set_enabled(False)
        self.del_all_btn.set_enabled(False)

    def __str__(self):
        return 'lineprofile'
