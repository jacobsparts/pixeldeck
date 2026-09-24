export function createImage(url) {
	return new Promise((resolve, reject) => {
		const img = new Image();
		img.onload = () => resolve(img);
		img.onerror = reject;
		img.src = url;
	});
}

import { dropdownMenu } from './dropdown-menu.js';

export const pixeldeckEditor = {
	name: 'pixeldeck-editor',
	components: { 'dropdown-menu': dropdownMenu },
	props: {
		modelValue: { default: null },
		filename: { default: null },
		baseUrl: { type: String, default: '' },
		eventBus: { default: null },
		active: { type: Boolean, default: true },
	},
	emits: ['file', 'close', 'busy'],
	data(){ return {
		imageFile: null,
		internalFilename: 'image',
		busy: false,
		abort_controller: null,
		schema: null,
		app: "",
		options: {},
		showPane: false,
		paneFields: null,
		paneProvider: '',
		pica_loaded: false,
		history: [],
		future: [],
		width: 0,
		height: 0,
		image_masker: null,
		checked: null,
		imageURL: null,
		imageLoadPromise: null,
		imageLoadResolve: null,
		updatingFromModel: false,
		canceled: false,
		inBatch: false,
		configSections: null,
		showConfig: false,
		configBusy: false,
		configMessage: '',
		configError: '',
	}},
	created(){
		this.loadSchema();
	},
	mounted(){
		if(this.eventBus){
			this.eventBus.addEventListener('broadcast', this.listener);
		}
	},
	beforeUnmount(){
		if(this.eventBus){
			this.eventBus.removeEventListener('broadcast', this.listener);
		}
		if(this.imageURL){
			URL.revokeObjectURL(this.imageURL);
		}
	},
	methods: {
		async loadSchema(){
			const json = await (await fetch(this.baseUrl + 'schema')).json();
			this.schema = json;
			if(!this.schema[this.app]){
				this.app = Object.keys(json)[0];
			}
		},
		ensureModelHistory(image = this.modelValue){
			if(!image){
				return;
			}
			if(!image.history){
				image.history = [];
			}
			if(!image.future){
				image.future = [];
			}
			this.history = image.history;
			this.future = image.future;
		},
		newHistory(){
			if(this.modelValue){
				this.ensureModelHistory();
				if(this.imageFile){
					this.modelValue.history.push(this.imageFile);
				}
				this.modelValue.future.length = 0;
				return;
			}
			if(this.imageFile){
				this.history.push(this.imageFile);
			}
			this.future = [];
		},
		open(){
			this.$refs.fileInput.click();
		},
		async new_image(){
			const canvas = document.createElement('canvas');
			canvas.width = 1000;
			canvas.height = 1000;
			const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
			this.newHistory();
			this.internalFilename = 'new_image';
			this.imageFile = blob;
		},
		setImageURL(file){
			const oldURL = this.imageURL;
			this.image_masker = null;
			this.imageLoadPromise = null;
			this.imageLoadResolve = null;
			if(file){
				this.imageURL = URL.createObjectURL(file);
				this.imageLoadPromise = new Promise(resolve => {
					this.imageLoadResolve = resolve;
				});
			} else {
				this.imageURL = null;
			}
			if(oldURL && oldURL !== this.imageURL){
				setTimeout(() => URL.revokeObjectURL(oldURL), 1000);
			}
		},
		releaseImageURL(){
			if(this.imageURL){
				URL.revokeObjectURL(this.imageURL);
				this.imageURL = null;
			}
			this.image_masker = null;
			this.imageLoadPromise = null;
			this.imageLoadResolve = null;
		},
		syncModelImage(){
			const image = this.modelValue;
			if(!image?.file){
				return;
			}
			this.ensureModelHistory(image);
			if(image.file === this.imageFile && this.imageURL){
				return;
			}
			this.updatingFromModel = true;
			this.imageFile = image.file;
			this.setImageURL(image.file);
			this.$nextTick(() => {
				this.updatingFromModel = false;
			});
		},
		async setImageFileAndWait(blob){
			this.updatingFromModel = true;
			this.imageFile = blob;
			this.setImageURL(blob);
			if(this.modelValue){
				this.$emit('file', blob);
			}
			await this.$nextTick();
			this.updatingFromModel = false;
			await this.waitForImageMasker();
			await new Promise(resolve => requestAnimationFrame(() => resolve()));
		},
		load_image(e){
			this.newHistory();
			const file = this.imageFile = e.target.files[0];
			this.internalFilename = file.name.slice(0, file.name.lastIndexOf('.'));
		},
		drop(e){
			if(e.dataTransfer){
				this.newHistory();
				const file = this.imageFile = e.dataTransfer.files[0];
				this.internalFilename = file.name.slice(0, file.name.lastIndexOf('.'));
			}
		},
		async getMaskBoundingBox(maskBlob){
			const url = URL.createObjectURL(maskBlob);
			const img = await createImage(url);
			const canvas = document.createElement('canvas');
			canvas.width = img.width;
			canvas.height = img.height;
			const ctx = canvas.getContext('2d');
			ctx.drawImage(img, 0, 0);
			URL.revokeObjectURL(url);
			const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
			const data = imageData.data;
			let minX = canvas.width, minY = canvas.height, maxX = -1, maxY = -1;
			for (let y = 0; y < canvas.height; y++) {
				for (let x = 0; x < canvas.width; x++) {
					if (data[(y * canvas.width + x) * 4] > 0) {
						minX = Math.min(minX, x);
						maxX = Math.max(maxX, x);
						minY = Math.min(minY, y);
						maxY = Math.max(maxY, y);
					}
				}
			}
			if (maxX < 0) return null;
			return { x: minX, y: minY, w: maxX + 1 - minX, h: maxY + 1 - minY };
		},
		async go(e,maskBlob, { silent = false } = {}){
			this.busy = true;
			await this.waitForImageMasker();
			if(this.canceled){
				this.busy = false;
				return;
			}
			if(!maskBlob){
				const blob = await this.image_masker.maskBlob;
				return this.go(e, blob, { silent });
			}
			if(this.canceled){
				this.busy = false;
				return;
			}
			const controller = this.abort_controller = new AbortController();
			if(this.canceled){
				controller.abort();
			}
			if(this.canceled){
				this.busy = false;
				return;
			}
			const canvas = document.createElement('canvas');
			canvas.width = this.width;
			canvas.height = this.height;
			const ctx = canvas.getContext('2d');
			ctx.fillStyle = 'rgb(255, 255, 255)';
			ctx.fillRect(0, 0, canvas.width, canvas.height);
			await this.withImage((image)=>{ctx.drawImage(image, 0, 0)});

			let cropBox = null;
			if (this.app === 'Background Removal') {
				cropBox = await this.getMaskBoundingBox(maskBlob);
			}

			let imageBlob;
			if (cropBox) {
				const cropCanvas = document.createElement('canvas');
				cropCanvas.width = cropBox.w;
				cropCanvas.height = cropBox.h;
				const cropCtx = cropCanvas.getContext('2d');
				cropCtx.drawImage(canvas, cropBox.x, cropBox.y, cropBox.w, cropBox.h, 0, 0, cropBox.w, cropBox.h);
				imageBlob = await new Promise(resolve => cropCanvas.toBlob(resolve, 'image/png'));
				cropCanvas.width = 0;
				cropCanvas.height = 0;
			} else {
				imageBlob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
			}
			canvas.width = 0;
			canvas.height = 0;

			if(this.canceled){
				this.busy = false;
				return;
			}
			const formData = new FormData();
			formData.append('image', imageBlob, 'file.png');
			formData.append('mask', maskBlob, 'blob');
			formData.append('app', this.app);
			for (const [k,v] of Object.entries(this.options)){
				formData.append(k,v);
			}
			return fetch(this.baseUrl + 'process', {
				method: 'POST',
				body: formData,
				signal: controller.signal,
			})
			.then(response => {
				if (response.ok) {
					return response.blob();
				} else {
					return response.text().then(body => {
						throw new Error(`${response.status} ${response.statusText}\n${body}`);
					});
				}
			})
			.then(async blob => {
				if(this.canceled){
					return;
				}
				if (cropBox) {
					const resultUrl = URL.createObjectURL(blob);
					const resultImg = await createImage(resultUrl);
					const compCanvas = document.createElement('canvas');
					compCanvas.width = this.width;
					compCanvas.height = this.height;
					const compCtx = compCanvas.getContext('2d');
					await this.withImage((image)=>{compCtx.drawImage(image, 0, 0)});
					compCtx.clearRect(cropBox.x, cropBox.y, cropBox.w, cropBox.h);
					compCtx.drawImage(resultImg, cropBox.x, cropBox.y);
					URL.revokeObjectURL(resultUrl);
					blob = await new Promise(resolve => compCanvas.toBlob(resolve, 'image/png'));
					compCanvas.width = 0;
					compCanvas.height = 0;
				}
				if(this.canceled){
					return;
				}
				this.newHistory();
				await this.setImageFileAndWait(blob);
			})
			.catch(error => {
				if(error.name !== 'AbortError' && !silent && this.active && !this.inBatch){
					alert(error);
				}
				this.busy = false;
				throw error;
			})
		},
		cancel(){
			this.canceled = true;
			if(this.abort_controller){
				this.abort_controller.abort();
			}
			this.busy = false;
		},
		processFromMenu(appName, model){
			this.app = appName;
			const providers = this.schema[appName] || {};
			const paneProvider = model
				? (Object.entries(providers).find(([p, s]) => s.model.options.includes(model))?.[0] || '')
				: (Object.keys(providers)[0] || '');
			const schema = providers[paneProvider] || {};
			const options = {};
			const fields = {};
			for (const [k,v] of Object.entries(schema)){
				options[k] = v.default;
				if (k === 'model') continue;
				const selected = model || options.model;
				if (Array.isArray(v.models) && selected && !v.models.includes(selected)) continue;
				if (Array.isArray(v.exclude_models) && selected && v.exclude_models.includes(selected)) continue;
				fields[k] = v;
			}
			if(model) options.model = model;
			this.options = options;
			if (Object.keys(fields).length > 0) {
				this.paneFields = fields;
				this.paneProvider = paneProvider;
				this.showPane = true;
			} else {
				this.showPane = false;
				this.canceled = false;
				this.go();
			}
		},
		async runProcess(appName, model, { silent = false } = {}){
			if(!this.imageFile || this.busy){return}
			this.app = appName;
			const options = {};
			for (const schema of Object.values(this.schema[appName] || {})) {
				for (const [k,v] of Object.entries(schema)){
					options[k] = options[k] || v.default;
				}
			}
			if(model) options.model = model;
			this.options = options;
			this.showPane = false;
			this.canceled = false;
			await this.go(null, null, { silent });
		},
		async photoBoxMacro(model = 'Single Item'){
			if(!this.imageFile || this.busy){return}
			try {
				this.app = 'Auto-Crop';
				this.options = { model };
				this.showPane = false;
				this.canceled = false;
				await this.go(null, null, { silent: false });
				if(this.canceled){return}
				await this.runProcess('Background Removal', 'RMBG-2.0');
				if(this.canceled){return}
				await this.crop();
				if(this.canceled){return}
				await this.resize(2048);
			} catch(error) {
				this.busy = false;
				throw error;
			}
		},
		paneGo(){
			this.showPane = false;
			this.canceled = false;
			this.go();
		},
		closePane(){
			this.showPane = false;
		},
		configFields(view){
			return view.sections.map(section => ({
				name: section.name,
				fields: section.fields.map(field => ({
					...field,
					// A secret is write-only, so its input always starts empty.
					input: field.secret ? '' : (field.value || ''),
					dirty: false,
				})),
			}));
		},
		async openConfig(){
			this.showConfig = true;
			this.configMessage = '';
			this.configError = '';
			const resp = await fetch(this.baseUrl + 'config');
			this.configSections = this.configFields(await resp.json());
		},
		closeConfig(){
			this.showConfig = false;
		},
		async saveConfig(){
			const patch = {};
			for(const section of this.configSections){
				for(const field of section.fields){
					if(!field.dirty){continue}
					(patch[section.name] = patch[section.name] || {})[field.key] = field.input === '' ? null : field.input;
				}
			}
			if(!Object.keys(patch).length){
				this.configMessage = 'Nothing changed';
				return;
			}
			this.configBusy = true;
			this.configError = '';
			this.configMessage = '';
			try {
				const resp = await fetch(this.baseUrl + 'config', {
					method: 'PUT',
					headers: {'Content-Type': 'application/json'},
					body: JSON.stringify(patch),
				});
				const body = await resp.text();
				if(!resp.ok){
					throw new Error(body);
				}
				this.configSections = this.configFields(JSON.parse(body));
				// Tools appear and disappear with their credentials, so the
				// menus have to be rebuilt from the schema.
				await this.loadSchema();
				this.configMessage = 'Saved';
			} catch(error) {
				this.configError = String(error.message || error);
			} finally {
				this.configBusy = false;
			}
		},
		async downloadPNG(){
			await this.waitForImageMasker();
			const blob = await this.image_masker.imageBlob;
			const url = URL.createObjectURL(blob);
			const downloadLink = document.createElement('a');
			downloadLink.href = url;
			downloadLink.download = `${this.effectiveFilename}.png`;
			downloadLink.click();
			URL.revokeObjectURL(url);
		},
		async downloadJPG(){
			await this.waitForImageMasker();
			const canvas = document.createElement('canvas');
			canvas.width = this.width;
			canvas.height = this.height;
			const ctx = canvas.getContext('2d');
			ctx.fillStyle = 'rgb(255, 255, 255)';
			ctx.fillRect(0, 0, canvas.width, canvas.height);
			await this.withImage((image)=>{ctx.drawImage(image, 0, 0)});
			const downloadLink = document.createElement('a');
			downloadLink.href = canvas.toDataURL('image/jpeg', 0.95);
			downloadLink.download = `${this.effectiveFilename}.jpg`;
			downloadLink.click();
		},
		async addToZip(zip) {
			await this.waitForImageMasker();
			const canvas = document.createElement('canvas');
			canvas.width = this.width;
			canvas.height = this.height;
			const ctx = canvas.getContext('2d');
			ctx.fillStyle = 'rgb(255, 255, 255)';
			ctx.fillRect(0, 0, canvas.width, canvas.height);
			await this.withImage((image) => {
				ctx.drawImage(image, 0, 0);
			});
			const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.95));
			zip.file(`${this.effectiveFilename}.jpg`, blob);
		},
		async downloadMask(){
			await this.waitForImageMasker();
			const blob = await this.image_masker.maskBlob;
			const url = URL.createObjectURL(blob);
			const downloadLink = document.createElement('a');
			downloadLink.href = url;
			downloadLink.download = `${this.maskFilename}.png`;
			downloadLink.click();
			URL.revokeObjectURL(url);
		},
		async imageLoad(e){
			this.image_masker = e.target;
			this.width = e.target.width;
			this.height = e.target.height;
			this.busy = false;
			if(this.imageLoadResolve){
				this.imageLoadResolve(e.target);
				this.imageLoadResolve = null;
				this.imageLoadPromise = null;
			}
		},
		waitForImageMasker(){
			if(this.image_masker){
				return Promise.resolve(this.image_masker);
			}
			if(!this.imageLoadPromise){
				this.imageLoadPromise = new Promise(resolve => {
					this.imageLoadResolve = resolve;
				});
			}
			return this.imageLoadPromise;
		},
		async withImage(fn){
			await this.waitForImageMasker();
			const imageBlob = await this.image_masker.imageBlob;
			const imageURL = URL.createObjectURL(imageBlob);
			const image = await createImage(imageURL);
			const resp = await fn(image);
			URL.revokeObjectURL(imageURL);
			return resp;
		},
		async crop(){
			await this.waitForImageMasker();
			this.busy = true;
			await new Promise(resolve => setTimeout(resolve, 0));
			const canvas = this.image_masker.canvas, ctx = this.image_masker.ctx;
			const imageData = await this.image_masker.imageData;
			const data = imageData.data;
			let minX = canvas.width, minY = canvas.height;
			let maxX = -1, maxY = -1;
			for (let y = 0; y < canvas.height; y++) {
				for (let x = 0; x < canvas.width; x++) {
					const alpha = data[(canvas.width * y + x) * 4 + 3];
					if (alpha !== 0) {
						minX = Math.min(minX, x);
						maxX = Math.max(maxX, x);
						minY = Math.min(minY, y);
						maxY = Math.max(maxY, y);
					}
				}
			}
			minX = Math.max(minX - 10, 0);
			minY = Math.max(minY - 10, 0);
			maxX = Math.min(maxX + 10, canvas.width - 1);
			maxY = Math.min(maxY + 10, canvas.height - 1);
			const width = maxX + 1 - minX;
			const height = maxY + 1 - minY;
			const croppedData = ctx.getImageData(minX, minY, width, height);
			canvas.width = width;
			canvas.height = height;
			ctx.putImageData(croppedData, 0, 0);
			const blob = await new Promise(resolve => canvas.toBlob(resolve));
			canvas.width = 0;
			canvas.height = 0;
			this.newHistory();
			await this.setImageFileAndWait(blob);
		},
		async rotate(angle) {
			await this.waitForImageMasker();
			this.busy = true;
			await new Promise(resolve => setTimeout(resolve, 0));
			const canvas = document.createElement('canvas');
			const ctx = canvas.getContext('2d');
			if (Math.abs(angle) === 90) {
				canvas.width = this.height;
				canvas.height = this.width;
			} else {
				canvas.width = this.width;
				canvas.height = this.height;
			}
			ctx.translate(canvas.width / 2, canvas.height / 2);
			ctx.rotate(angle * Math.PI / 180);
			await this.withImage((image)=>{
				ctx.drawImage(image, -this.width / 2, -this.height / 2);
			});
			const blob = await new Promise(resolve => canvas.toBlob(resolve));
			canvas.width = 0;
			canvas.height = 0;
			this.newHistory();
			await this.setImageFileAndWait(blob);
		},
		async resize(size){
			await this.waitForImageMasker();
			this.busy = true;
			await new Promise(resolve => setTimeout(resolve, 0));
			if(!this.pica_loaded){
				await import('./pica.min.js');
				this.pica_loaded = true;
			}
			const canvas = document.createElement('canvas')
			if(this.width >= this.height){
				canvas.width  = size;
				canvas.height = ( this.height / this.width ) * size;
			} else {
				canvas.width  = ( this.width / this.height ) * size;
				canvas.height = size;
			}
			await window.pica().resize(this.image_masker.canvas, canvas, {
				filter: 'lanczos3',
			});
			const canvas2 = document.createElement('canvas')
			canvas2.width  = size;
			canvas2.height = size;
			const ctx = canvas2.getContext('2d');
			const dx = (canvas2.width - canvas.width) / 2;
			const dy = (canvas2.height - canvas.height) / 2;
			ctx.drawImage(canvas, dx, dy, canvas.width, canvas.height);
			const blob = await new Promise(resolve => canvas2.toBlob(resolve));
			canvas.width = 0;
			canvas.height = 0;
			canvas2.width = 0;
			canvas2.height = 0;
			this.newHistory();
			await this.setImageFileAndWait(blob);
		},
		async resizeLongEdge(size){
			await this.waitForImageMasker();
			this.busy = true;
			await new Promise(resolve => setTimeout(resolve, 0));
			if(!this.pica_loaded){
				await import('./pica.min.js');
				this.pica_loaded = true;
			}
			const canvas = document.createElement('canvas');
			if(this.width >= this.height){
				canvas.width  = size;
				canvas.height = Math.round(( this.height / this.width ) * size);
			} else {
				canvas.width  = Math.round(( this.width / this.height ) * size);
				canvas.height = size;
			}
			await window.pica().resize(this.image_masker.canvas, canvas, {
				filter: 'lanczos3',
			});
			const blob = await new Promise(resolve => canvas.toBlob(resolve));
			canvas.width = 0;
			canvas.height = 0;
			this.newHistory();
			await this.setImageFileAndWait(blob);
		},
		async undo(){
			if(!this.history.length){return}
			this.future.push(this.imageFile);
			const blob = this.history.pop();
			await this.setImageFileAndWait(blob);
		},
		async redo(){
			if(!this.future.length){return}
			this.history.push(this.imageFile);
			const blob = this.future.pop();
			await this.setImageFileAndWait(blob);
		},
		async cropBox() {
			await this.waitForImageMasker();
			this.busy = true;
			const maskBlob = await this.image_masker.maskBlob;
			const box = await this.getMaskBoundingBox(maskBlob);
			if (!box) { this.busy = false; return; }
			const canvas = document.createElement('canvas');
			canvas.width = box.w;
			canvas.height = box.h;
			const ctx = canvas.getContext('2d');
			await this.withImage((image) => {
				ctx.drawImage(image, box.x, box.y, box.w, box.h, 0, 0, box.w, box.h);
			});
			const blob = await new Promise(resolve => canvas.toBlob(resolve));
			canvas.width = 0;
			canvas.height = 0;
			this.newHistory();
			await this.setImageFileAndWait(blob);
		},
		async erase() {
			await this.waitForImageMasker();
			this.busy = true;
			try {
				const canvas = document.createElement('canvas');
				canvas.width = this.width;
				canvas.height = this.height;
				const ctx = canvas.getContext('2d');
				await this.withImage((image)=>{ctx.drawImage(image, 0, 0)});

				const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
				const maskData = this.image_masker.maskAlphaImageData.data;
				const data = imageData.data;
				let erased = 0;
				for(let i = 0; i < data.length; i += 4){
					if(maskData[i] || maskData[i + 1] || maskData[i + 2] || maskData[i + 3]){
						data[i + 3] = 0;
						erased++;
					}
				}
				if(!erased){
					return;
				}
				ctx.putImageData(imageData, 0, 0);
				this.newHistory();
				const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
				canvas.width = 0;
				canvas.height = 0;
				await this.setImageFileAndWait(blob);
			} finally {
				this.busy = false;
			}
		},
		async listener(event){
			const detail = Array.isArray(event.detail) ? {args: event.detail} : event.detail;
			const args = [...detail.args];
			const method = args.shift();
			if(method === 'cancel'){
				if(detail.cancelAll || detail.targetId == null || this.modelValue?.id === detail.targetId){
					return this.cancel();
				}
				return;
			}
			if(detail.targetId != null && this.modelValue?.id !== detail.targetId){return}
			if(!this.checked){return}
			this.canceled = false;
			this.syncModelImage();
			await this.$nextTick();
			await this.waitForImageMasker();
			if(this.canceled){
				return;
			}
			this.inBatch = true;
			try {
				if(this.schema[method]){
					this.app = method;
					const options = {};
					for (const [provider,schema] of Object.entries(this.schema[method])) {
						for (const [k,v] of Object.entries(schema)){
							options[k] = options[k] || v.default;
						}
					}
					if(args[0]) Object.assign(options, args[0]);
					this.options = options;
					return await this.go();
				} else {
					return await this[method](...args);
				}
			} finally {
				this.inBatch = false;
				if(!this.active){
					await this.$nextTick();
					if(this.imageURL){
						await this.waitForImageMasker();
					}
					this.releaseImageURL();
					await this.$nextTick();
				}
			}
		},
	},
	computed: {
		appMenus(){
			if(!this.schema) return [];
			return Object.entries(this.schema).map(([app, providers]) => {
				const models = [];
				for(const [provider, s] of Object.entries(providers)){
					for(const model of s.model.options){
						models.push({model, provider});
					}
				}
				return { app, models };
			});
		},
		photoBoxOptions(){
			return [
				{ text: 'Single Item', fn: () => this.photoBoxMacro('Single Item') },
				{ text: 'Kit / Multi-Item', fn: () => this.photoBoxMacro('Kit / Multi-Item') },
				{ text: 'Light Item', fn: () => this.photoBoxMacro('Light Item') },
			];
		},
		resizeOptions(){
			const sizes = [512, 768, 1024, 2048];
			return [
				...sizes.map(s => ({text: `Resize ${s}\u00d7${s}`, fn: () => this.resize(s)})),
				...sizes.map(s => ({text: `Resize ${s} long edge`, fn: () => this.resizeLongEdge(s)})),
			];
		},
		effectiveFilename(){
			if(this.filename != null) return this.filename;
			return this.internalFilename + '_out';
		},
		maskFilename(){
			return (this.filename != null ? this.filename : this.internalFilename) + '_mask';
		},
		imageDataUrl(){
			return this.imageURL;
		},
		isPNG(){
			return this.imageFile?.type.startsWith('image/png');
		},
	},
	watch: {
		modelValue: {
			handler(image){
				if(!image) return;
				this.ensureModelHistory(image);
				this.checked = image.checked;
				if(this.active){
					this.syncModelImage();
				}
			},
			immediate: true,
			deep: true,
		},
		active(val){
			if(val){
				this.syncModelImage();
			} else if(this.modelValue && !this.busy){
				this.releaseImageURL();
			}
		},
		imageFile(file){
			if(this.updatingFromModel){
				return;
			}
			this.setImageURL(file);
			if(this.modelValue){
				this.$emit('file', file);
			}
		},
		busy(val){
			this.$emit('busy', val);
		},
	},
	template: `<div id="container" v-if="schema">

<div v-if="active" class="editor-menubar" :class="{disabled: busy}">
	<div v-if="!modelValue" class="sep"></div>
	<span v-if="modelValue" class="shortcut" @click="$emit('close')">Close</span>
	<span v-else class="shortcut" @click="open">Open</span>
	<span class="shortcut" @click="new_image">New</span>
	<div class="sep"></div>

	<template v-for="(group, gi) in appMenus">
		<div v-if="group.models.length === 1" class="menu"><div class="menu-trigger" @click="processFromMenu(group.app, group.models[0].model)">{{ group.app }}</div></div>
		<dropdown-menu v-else :label="group.app" :items="group.models" @select="m => processFromMenu(group.app, m.model)">
			<template #item="{item}">{{ item.provider }}: {{ item.model }}</template>
		</dropdown-menu>
	</template>

	<div class="sep"></div>
	<dropdown-menu :class="{disabled: !imageFile || busy}" label="Photo Box 2048" :items="photoBoxOptions" @select="item => item.fn()">
		<template #item="{item}">{{ item.text }}</template>
	</dropdown-menu>
	<div class="sep"></div>
	<span class="shortcut" :class="{disabled: !imageFile || !isPNG}" @click="crop">Crop</span>
	<dropdown-menu label="Resize" :items="resizeOptions" @select="item => item.fn()">
		<template #item="{item}">{{ item.text }}</template>
	</dropdown-menu>
	<span class="shortcut" :class="{disabled: !imageFile}" @click="rotate(-90)" title="Rotate -90\u00b0">\u2ba6</span>
	<span class="shortcut" :class="{disabled: !imageFile}" @click="rotate(90)" title="Rotate 90\u00b0">\u2ba7</span>
	<div class="sep"></div>
	<span class="shortcut" :class="{disabled: !imageFile}" @click="downloadPNG">\u2b07 PNG</span>
	<span class="shortcut" :class="{disabled: !imageFile || !isPNG}" @click="downloadJPG">\u2b07 JPG</span>
	<div class="sep"></div>
	<span class="shortcut" :class="{disabled: !history.length}" @click="undo" title="Undo">\u21b6</span>
	<span class="shortcut" :class="{disabled: !future.length}" @click="redo" title="Redo">\u21b7</span>
	<template v-if="width">
		<div class="sep"></div>
		<span class="dim">{{ width }}\u00d7{{ height }}</span>
	</template>
	<div class="sep"></div>
	<span class="shortcut" @click="openConfig" title="Provider configuration">Config</span>
</div>
<div v-if="active && busy" class="editor-menubar" style="justify-content: center; position: absolute; left: 0; right: 0; z-index: 50; opacity: 0.85;">
	<span v-if="modelValue" class="shortcut" @click="$emit('close')" style="position: absolute; left: 0.25rem;">Close</span>
	<span class="shortcut" @click="cancel">Cancel</span>
</div>

<div id="image-container">
	<div v-if="active && !imageDataUrl">click to browse<br> or drag file here</div>
	<input v-if="active" ref="fileInput" type="file" accept="*/*" @change="load_image" style="width: 100%; height: 100%; opacity: 0; position: absolute; cursor: pointer;" :disabled="busy"/>
	<image-masker v-if="active || imageDataUrl" v-show="imageDataUrl" :src="imageDataUrl" :headless="!active && modelValue" :class="{busy: busy}" @load="imageLoad" @drop="drop" @erase="erase" @cropbox="cropBox" @downloadmask="downloadMask"></image-masker>
</div>
<div v-if="showPane" class="modal-backdrop" @click.self="closePane">
	<div class="modal">
		<div class="modal-header">
			<span>{{ paneProvider }}: {{ options.model }}</span>
			<span class="shortcut" @click="closePane">\u2715</span>
		</div>
		<div class="modal-body">
			<template v-for="(field, key) in paneFields" :key="key">
				<label class="modal-label">{{ key }}</label>
				<template v-if="field.type === 'string'">
					<textarea class="modal-textarea" v-model="options[key]" :placeholder="key" rows="6"></textarea>
					<div v-if="field.presets" class="modal-presets">
						<span v-for="(val, name) in field.presets" :key="name" class="modal-preset" @click="options[key] = val">{{ name }}</span>
					</div>
				</template>
				<select v-else-if="field.type === 'enum'" class="modal-select" v-model="options[key]">
					<option v-for="opt in field.options" :key="opt" :value="opt">{{ opt }}</option>
				</select>
			</template>
		</div>
		<button class="modal-go" :disabled="busy" @click="paneGo">Go</button>
	</div>
</div>
<div v-if="showConfig" class="modal-backdrop" @click.self="closeConfig">
	<div class="modal">
		<div class="modal-header">
			<span>Configuration</span>
			<span class="shortcut" @click="closeConfig">\u2715</span>
		</div>
		<div class="modal-body" v-if="configSections">
			<p class="config-hint">Credentials for the image APIs. A provider without credentials is simply not offered. This writes config.json; secrets are never sent back to the browser.</p>
			<div v-for="section in configSections" :key="section.name" class="config-section">
				<div class="config-section-name">{{ section.name }}</div>
				<label v-for="field in section.fields" :key="field.key" class="config-field">
					<span class="config-field-name">{{ field.key }}</span>
					<input class="config-input" :type="field.secret ? 'password' : 'text'" v-model="field.input" @input="field.dirty = true" autocomplete="off" :placeholder="field.set ? '(configured)' : '(not set)'"/>
				</label>
			</div>
			<p class="config-hint">Clear a field and save to remove that setting.</p>
			<p v-if="configError" class="config-error">{{ configError }}</p>
			<p v-else-if="configMessage" class="config-message">{{ configMessage }}</p>
		</div>
		<button class="modal-go" :disabled="configBusy" @click="saveConfig">Save</button>
	</div>
</div>
</div>`
};
